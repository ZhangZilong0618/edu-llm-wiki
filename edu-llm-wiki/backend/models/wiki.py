from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class WikiPage(BaseModel):
    path: str  # relative path within wiki/
    title: str
    page_type: str  # concept | formula | principle | exercise | source | synthesis
    content: str
    sources: list[str] = []  # source file references
    tags: list[str] = []
    created: str = ""
    updated: str = ""


class WikiPageCreate(BaseModel):
    title: str
    page_type: str = "concept"
    content: str
    sources: list[str] = []
    tags: list[str] = []


class WikiPageUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    sources: Optional[list[str]] = None
    tags: Optional[list[str]] = None


class WikiIndex(BaseModel):
    pages: list[dict]  # [{path, title, type, summary}]
    updated: str


class IngestRequest(BaseModel):
    source_paths: list[str]  # paths relative to sources/
    force: bool = False  # re-process even if cached


class IngestResult(BaseModel):
    source: str
    status: str  # cached | analyzed | generated | error
    wiki_pages_created: list[str] = []
    wiki_pages_updated: list[str] = []
    concepts_extracted: list[str] = []
    error: str = ""
