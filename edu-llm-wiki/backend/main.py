"""Edu-LLM-Wiki: Educational Knowledge Base System."""

import shutil
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from routes import chat, conversations, graph, ingest, lint, projects, search, settings_api, wiki
from storage.wiki_store import ensure_dirs

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
app.include_router(chat.router)
app.include_router(wiki.router)
app.include_router(lint.router)
app.include_router(projects.router)
app.include_router(conversations.router)
app.include_router(settings_api.router)


@app.on_event("startup")
async def startup():
    _migrate_to_projects()
    ensure_dirs(project_id="default")
    # Auto-build vector index for all projects if missing
    _ensure_vector_indices()


def _ensure_vector_indices():
    """Build vector index for any project that doesn't have one yet."""

    from services.vector_store import index_pages, table_exists
    from storage.wiki_store import list_projects, list_wiki_pages, read_wiki_page

    try:
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
