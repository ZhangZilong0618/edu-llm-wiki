"""API routes for knowledge graph."""

from fastapi import APIRouter, Query
from models.graph import GraphData, GraphInsight
from services.graph_engine import build_graph, get_node_neighborhood

router = APIRouter(prefix="/api/graph", tags=["graph"])


@router.get("", response_model=GraphData)
async def get_graph(project_id: str = Query("default")):
    """Get the full knowledge graph with communities and insights."""
    return build_graph(project_id=project_id)


@router.get("/neighborhood/{node_id}")
async def get_neighborhood(node_id: str, depth: int = Query(1, ge=1, le=3), project_id: str = Query("default")):
    """Get a node and its neighbors."""
    return get_node_neighborhood(node_id, depth, project_id=project_id)


@router.get("/insights")
async def get_insights(project_id: str = Query("default")):
    """Get graph insights only."""
    graph = build_graph(project_id=project_id)
    return graph.get("insights", [])
