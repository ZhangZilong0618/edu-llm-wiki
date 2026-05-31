"""Edu-LLM-Wiki: Educational Knowledge Base System."""

import shutil
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from config import settings
from storage.wiki_store import ensure_dirs, wiki_path, sources_path
from routes import ingest, search, graph, chat, wiki, lint, projects, settings_api


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
app.include_router(settings_api.router)


@app.on_event("startup")
async def startup():
    _migrate_to_projects()
    ensure_dirs(project_id="default")


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
