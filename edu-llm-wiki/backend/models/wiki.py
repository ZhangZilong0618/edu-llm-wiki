
from pydantic import BaseModel


class WikiPage(BaseModel):
    path: str  # relative path within wiki/
    title: str
    page_type: str  # concept | formula | principle | source | synthesis | inquiry | guide
    content: str
    sources: list[str] = []  # source file references
    tags: list[str] = []
    created: str = ""
    updated: str = ""
    # --- v2 structured fields (all optional, backward compatible) ---
    difficulty: int | None = None           # 1..5, cognitive load for a beginner
    prerequisites: list[str] = []          # paths that must be understood first
    related: list[str] = []                # same-level associations
    common_misconceptions: list[str] = []  # concept page only
    worked_example_ref: list[str] = []     # concept page → formula pages as examples
    last_reviewed: str = ""                # ISO datetime, for spaced review


class WikiPageCreate(BaseModel):
    title: str
    page_type: str = "concept"
    content: str
    sources: list[str] = []
    tags: list[str] = []
    difficulty: int | None = None
    prerequisites: list[str] = []
    related: list[str] = []
    common_misconceptions: list[str] = []
    worked_example_ref: list[str] = []
    last_reviewed: str = ""


class WikiPageUpdate(BaseModel):
    title: str | None = None
    content: str | None = None
    sources: list[str] | None = None
    tags: list[str] | None = None
    difficulty: int | None = None
    prerequisites: list[str] | None = None
    related: list[str] | None = None
    common_misconceptions: list[str] | None = None
    worked_example_ref: list[str] | None = None
    last_reviewed: str | None = None


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
