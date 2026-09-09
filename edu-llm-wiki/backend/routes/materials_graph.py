"""API routes for the materials-science domain graph extractor."""

from fastapi import APIRouter, HTTPException

from models.materials_graph import (
    MaterialsGraphData,
    MaterialsGraphExtractRequest,
    MaterialsGraphPageRequest,
)
from services.materials_graph import extract_materials_graph
from storage.wiki_store import read_wiki_page

router = APIRouter(prefix="/api/materials-graph", tags=["materials graph"])


@router.post("/extract", response_model=MaterialsGraphData)
async def extract_materials_graph_endpoint(request: MaterialsGraphExtractRequest) -> MaterialsGraphData:
    """Extract a materials-science domain graph from raw course text."""
    try:
        graph = await extract_materials_graph(
            request.content,
            source_title=request.source_title,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"LLM extraction failed: {exc}") from exc
    return MaterialsGraphData(**graph)


@router.post("/from-page", response_model=MaterialsGraphData)
async def extract_materials_graph_from_page(request: MaterialsGraphPageRequest) -> MaterialsGraphData:
    """Extract a materials-science domain graph from an existing wiki page."""
    page = read_wiki_page(request.page_path, project_id=request.project_id)
    if not page:
        raise HTTPException(status_code=404, detail="Wiki page not found")

    source_title = str(page.get("title") or request.page_path)
    content = str(page.get("content") or "")
    try:
        graph = await extract_materials_graph(content, source_title=source_title)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"LLM extraction failed: {exc}") from exc
    return MaterialsGraphData(**graph)
