"""API routes for search."""

from fastapi import APIRouter, Query

from models.search import SearchResponse
from services.search_engine import search

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("", response_model=SearchResponse)
async def search_endpoint(
    q: str = Query(..., description="Search query"),
    vector: bool = Query(False, description="Enable vector search"),
    top_k: int = Query(20, ge=1, le=50, description="Max results"),
    project_id: str = Query("default"),
):
    """Multi-phase search over wiki pages."""
    return await search(q, include_vector=vector, top_k=top_k, project_id=project_id)
