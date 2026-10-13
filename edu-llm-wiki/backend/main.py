"""Edu-LLM-Wiki: Educational Knowledge Base System."""

import asyncio
import logging
import shutil
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from routes import (
    chat,
    conversations,
    graph,
    ingest,
    learning,
    materials_graph,
    ontology,
    projects,
    research,
    search,
    settings_api,
    tests,
    wiki,
)
from storage.wiki_store import ensure_dirs, list_projects

_LOGGER = logging.getLogger(__name__)

app = FastAPI(
    title="Edu-LLM-Wiki",
    description="AI-powered educational knowledge base system",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routes
app.include_router(ingest.router)
app.include_router(search.router)
app.include_router(graph.router)
app.include_router(materials_graph.router)
app.include_router(chat.router)
app.include_router(wiki.router)
app.include_router(projects.router)
app.include_router(conversations.router)
app.include_router(settings_api.router)
app.include_router(research.router)
app.include_router(tests.router)
app.include_router(ontology.router)
app.include_router(learning.router)


@app.on_event("startup")
async def startup():
    _migrate_to_projects()
    _materialize_project_wikis()
    # Build vector indexes in the background so a slow embedding model or a
    # large existing Wiki does not delay the HTTP server from becoming ready.
    _schedule_vector_index_build()
    app.state.wiki_projection_task = asyncio.create_task(_retry_wiki_projections())


@app.on_event("shutdown")
async def shutdown():
    vector_task = getattr(app.state, "vector_index_task", None)
    if vector_task is not None and not vector_task.done():
        vector_task.cancel()
    projection_task = getattr(app.state, "wiki_projection_task", None)
    if projection_task is not None and not projection_task.done():
        projection_task.cancel()

    # SQLite only checkpoints a WAL database when the *last* connection to it
    # closes. graph_store caches one connection per project for the lifetime of
    # the process, so nothing ever triggered that checkpoint: the -wal file kept
    # growing past the main database and every read replayed it. Closing here
    # also flushes anything still un-checkpointed before the process exits.
    try:
        from services import graph_store

        graph_store.close_all()
    except Exception as exc:  # never block shutdown on cleanup
        print(f"[shutdown] graph_store.close_all failed: {exc}")

    # ABox worlds are cached per project and hold the ontology SQLite files
    # open for the lifetime of the process.  Flush taxonomy migrations and
    # learner assertions before releasing the process, otherwise a graceful
    # restart can lose the in-memory schema upgrade and leave the file locked.
    try:
        from services.ontology import abox

        abox.close_all()
    except Exception as exc:  # never block shutdown on cleanup
        print(f"[shutdown] ontology.abox.close_all failed: {exc}")


def _schedule_vector_index_build() -> None:
    """Schedule the initial vector-index build without blocking startup."""

    existing_task = getattr(app.state, "vector_index_task", None)
    if existing_task is not None and not existing_task.done():
        return

    task = asyncio.create_task(
        asyncio.to_thread(_ensure_vector_indices),
        name="vector-index-build",
    )
    app.state.vector_index_task = task
    task.add_done_callback(_report_vector_index_task)


def _report_vector_index_task(task: asyncio.Task) -> None:
    """Consume unexpected task errors so they do not become unhandled warnings."""

    try:
        task.result()
    except asyncio.CancelledError:
        return
    except Exception as exc:  # pragma: no cover - _ensure_vector_indices logs normal failures
        print(f"[vector] Background index build failed: {exc}")


def _ensure_vector_indices():
    """Build vector index for any project that doesn't have one yet."""

    from services.vector_store import index_pages, table_exists
    # Import lazily so startup module loading stays cheap.  Ingest workers use
    # this same process-wide lock when they create the first project table;
    # without sharing it, startup rebuild and first import could both drop and
    # recreate the same LanceDB table concurrently.
    from services.ingest_engine import _VECTOR_SYNC_LOCK
    from storage.wiki_store import list_projects, list_wiki_pages, read_wiki_page

    try:
        with _VECTOR_SYNC_LOCK:
            for proj in list_projects():
                pid = proj["name"]
                if table_exists(project_id=pid):
                    print(f"[vector] Index already exists for project '{pid}'")
                    continue
                pages = list_wiki_pages(project_id=pid)
                if not pages:
                    continue
                # Load full content for each page
                full_pages = []
                for p in pages:
                    data = read_wiki_page(p["path"], project_id=pid)
                    if data:
                        full_pages.append({
                            "path": p["path"],
                            "title": p["title"],
                            "type": p["type"],
                            "content": data.get("content", ""),
                        })
                if full_pages:
                    n = index_pages(full_pages, project_id=pid)
                    print(f"[vector] Built index for project '{pid}': {n} pages")
    except Exception as e:
        print(f"[vector] Index build skipped: {e}")


def _materialize_project_wikis() -> None:
    """Materialize the current Wiki layout for every existing project.

    ``ensure_dirs`` is idempotent and owns the ontology-derived TeachingObject
    directory.  Running it for all projects at startup upgrades projects that
    predate the taxonomy, while also keeping newly created projects on the
    same path.
    """
    project_ids = {project["name"] for project in list_projects()}
    project_ids.add("default")
    for project_id in sorted(project_ids):
        ensure_dirs(project_id=project_id)


async def _retry_wiki_projections() -> None:
    """Retry transient Wiki projection failures without blocking API work."""
    while True:
        await asyncio.sleep(30)
        try:
            from services.wiki_auto_update import replay_failed_events

            for project in list_projects():
                project_id = str(project["name"])
                try:
                    result = await asyncio.to_thread(replay_failed_events, project_id)
                    if result.get("events"):
                        _LOGGER.info(
                            "Replayed %s Wiki projection events for project=%s",
                            result["events"], project_id,
                        )
                except Exception as error:
                    _LOGGER.warning(
                        "Wiki projection retry failed project=%s error=%s",
                        project_id, type(error).__name__,
                    )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            _LOGGER.warning("Wiki projection retry cycle failed error=%s", type(error).__name__)


def _migrate_to_projects():
    """Auto-migrate data/wiki/ → data/projects/default/wiki/ and data/sources/ → data/projects/default/sources/."""
    projects_dir = Path(settings.projects_dir)
    default_proj = projects_dir / "default"
    new_wiki = default_proj / "wiki"
    new_sources = default_proj / "sources"

    # Only migrate if old locations exist and new locations don't
    old_wiki = Path(settings.data_dir) / "wiki"
    old_sources = Path(settings.data_dir) / "sources"

    if old_wiki.exists() and not new_wiki.exists():
        default_proj.mkdir(parents=True, exist_ok=True)
        shutil.move(str(old_wiki), str(new_wiki))
        print(f"[migration] Moved {old_wiki} → {new_wiki}")

    if old_sources.exists() and not new_sources.exists():
        default_proj.mkdir(parents=True, exist_ok=True)
        shutil.move(str(old_sources), str(new_sources))
        print(f"[migration] Moved {old_sources} → {new_sources}")


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}
