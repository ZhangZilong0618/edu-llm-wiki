"""Edu-LLM-Wiki: Educational Knowledge Base System."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from config import settings
from storage.wiki_store import ensure_dirs
from routes import ingest, search, graph, chat, wiki, lint, settings_api


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
app.include_router(settings_api.router)


@app.on_event("startup")
async def startup():
    ensure_dirs()


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}
