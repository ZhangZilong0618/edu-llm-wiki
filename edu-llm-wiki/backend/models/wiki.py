
from pydantic import BaseModel


class SourceRef(BaseModel):
    file: str
    page: int
    quote: str
    verified: bool
    offset_start: int | None = None
    offset_end: int | None = None


class UnverifiedRef(BaseModel):
    file: str
    page: int
    quote: str
    reason: str = ""


class WikiPage(BaseModel):
    path: str  # relative path within wiki/
    title: str
    page_type: str  # 12 types: source|concept|principle|formula|procedure|example|misconception|synthesis|learning_path|learning_objective|rubric
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
    # --- v3 citation fields (Stage 3 校验产物) ---
    source_refs: list[SourceRef] = []
    unverified_refs: list[UnverifiedRef] = []


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
    # v3: citation 字段在 create 时由后端派生，不接收客户端直传
    source_refs: list[SourceRef] | None = None
    unverified_refs: list[UnverifiedRef] | None = None


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


# ---------- Stage 触发（B/C 组按需生成）----------

class BStageRequest(BaseModel):
    """B 组应用页（example / misconception）按需生成请求。"""
    source_file: str
    page_types: list[str] = ["example", "misconception"]  # 默认两种都生成
    extra_context: str = ""


class CStageRequest(BaseModel):
    """C 组整合 / 评价页按需生成请求。"""
    page_type: str  # synthesis | learning_path | learning_objective | rubric
    target_pages: list[str] = []  # paths that anchor the generation
    extra_context: str = ""


class StageGenerateResult(BaseModel):
    pages_created: list[str] = []
    pages_updated: list[str] = []
    error: str = ""
