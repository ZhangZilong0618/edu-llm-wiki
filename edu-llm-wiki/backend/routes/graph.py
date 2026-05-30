"""API routes for knowledge graph."""

from fastapi import APIRouter, Query
from models.graph import GraphData, GraphInsight
from services.graph_engine import build_graph, get_node_neighborhood

router = APIRouter(prefix="/api/graph", tags=["graph"])


@router.get("", response_model=GraphData)
async def get_graph():
    """Get the full knowledge graph with communities and insights."""
    return build_graph()


@router.get("/neighborhood/{node_id}")
async def get_neighborhood(node_id: str, depth: int = Query(1, ge=1, le=3)):
    """Get a node and its neighbors."""
    return get_node_neighborhood(node_id, depth)


@router.get("/insights")
async def get_insights():
    """Get graph insights only."""
    graph = build_graph()
    return graph.get("insights", [])
