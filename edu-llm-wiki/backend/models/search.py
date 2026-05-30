from pydantic import BaseModel


class SearchResult(BaseModel):
    path: str
    title: str
    snippet: str
    score: float
    title_match: bool = False
    vector_score: float | None = None


class SearchResponse(BaseModel):
    mode: str  # keyword | vector | hybrid
    results: list[SearchResult]
    token_hits: int = 0
    vector_hits: int = 0
