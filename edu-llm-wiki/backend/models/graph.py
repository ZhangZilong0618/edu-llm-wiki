from pydantic import BaseModel, Field


# Allowed values are intentionally documented here. Keeping the comments in
# sync with the engine is a maintenance trap; models just accept any string
# and the engine validates at write time.
BLOOM_LEVELS = ["remember", "understand", "apply", "analyze", "evaluate", "create"]
MASTERY_LEVELS = ["new", "exposed", "learning", "proficient", "mastered"]
EDGE_TYPES = [
    "prerequisite",
    "teaches",
    "enables",
    "derives",
    "applies_to",
    "scaffolds",
    "related",
    "source",
    "direct",
]


class GraphNode(BaseModel):
    id: str
    label: str
    node_type: str
    size: int = 1
    community: int = -1
    metadata: dict = Field(default_factory=dict)
    # Learning-semantic fields (optional; older clients won't send these)
    bloom_level: str | None = None
    difficulty: int | None = Field(default=None, ge=1, le=5)
    estimated_minutes: float | None = None
    parent_concept: str | None = None
    tags: list[str] = Field(default_factory=list)
    mastery: str | None = None  # one of MASTERY_LEVELS or None
    mastery_score: float | None = None
    last_seen_at: float | None = None


class GraphEdge(BaseModel):
    source: str
    target: str
    edge_type: str
    weight: float = 1.0
    confidence: float = 1.0
    rationale: str | None = None
    signals: dict[str, float] = Field(default_factory=dict)
    source_kind: str | None = None  # wikilink | ingest | heuristic | manual


class GraphInsight(BaseModel):
    insight_type: str
    title: str
    description: str
    node_ids: list[str] = Field(default_factory=list)
    score: float = 0.0
    # Optional pedagogical context used by the learning UI
    suggested_actions: list[str] = Field(default_factory=list)


class GraphData(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    communities: list[dict] = Field(default_factory=list)
    insights: list[GraphInsight] = Field(default_factory=list)
    stats: dict = Field(default_factory=dict)


class GraphEvent(BaseModel):
    """Server-sent event payload for graph updates."""

    event: str
    project_id: str
    payload: dict = Field(default_factory=dict)
    ts: float = 0.0


class LearningPathStep(BaseModel):
    node_id: str
    label: str
    node_type: str
    depth: int
    edge_type: str  # how this node was reached from the previous one
    mastery: str | None = None
    estimated_minutes: float | None = None


class LearningPathResponse(BaseModel):
    target: str
    start: str | None = None
    steps: list[LearningPathStep]
    total_minutes: float = 0.0
    remaining: list[str] = Field(default_factory=list)


class MasteryAttemptRequest(BaseModel):
    node_id: str
    score: float = Field(ge=0.0, le=1.0)
    # Optional context about what produced the attempt — used to attribute
    # updates to tests vs chat vs explicit practice.
    origin: str | None = None  # "test" | "chat" | "practice" | "review"
    attempt_id: str | None = None


class MasteryExposureRequest(BaseModel):
    node_id: str
    duration_seconds: float = 0.0
    origin: str | None = None  # "page_open" | "search_hit" | "chat_mention"


class MasteryState(BaseModel):
    node_id: str
    level: str
    score: float
    attempts: int
    exposures: int
    last_attempt_at: float | None = None
    last_exposure_at: float | None = None
    promoted_at: float | None = None