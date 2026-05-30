from pydantic import BaseModel


class GraphNode(BaseModel):
    id: str
    label: str
    node_type: str  # concept | formula | principle | course | source
    size: int = 1
    community: int = -1
    metadata: dict = {}


class GraphEdge(BaseModel):
    source: str
    target: str
    edge_type: str  # prerequisite | derives | applies_to | related
    weight: float = 1.0


class GraphInsight(BaseModel):
    insight_type: str  # isolated | bridge | surprising_connection | knowledge_gap
    title: str
    description: str
    node_ids: list[str] = []
    score: float = 0.0


class GraphData(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    communities: list[dict] = []  # [{id, label, cohesion, member_count}]
    insights: list[GraphInsight] = []
