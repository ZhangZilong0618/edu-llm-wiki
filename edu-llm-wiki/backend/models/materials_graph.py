from pydantic import BaseModel, Field


class MaterialsGraphCourseProfile(BaseModel):
    course: str
    topic: str = ""
    chapters: list[dict] = Field(default_factory=list)
    prerequisite_courses: list[str] = Field(default_factory=list)
    core_competencies: list[str] = Field(default_factory=list)


class MaterialsGraphNode(BaseModel):
    id: str
    label: str
    node_type: str
    definition: str = ""
    source_ref: str | None = None
    difficulty: int | None = Field(default=None, ge=1, le=5)
    bloom_level: str | None = None
    prerequisites: list[str] = Field(default_factory=list)
    common_misconceptions: list[str] = Field(default_factory=list)
    learning_objectives: list[str] = Field(default_factory=list)
    estimated_minutes: float | None = None
    related_courses: list[str] = Field(default_factory=list)


class MaterialsGraphEdge(BaseModel):
    source: str
    target: str
    edge_type: str
    evidence: str = ""
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    weight: float = Field(default=0.7, ge=0.0, le=1.0)


class MaterialsGraphStats(BaseModel):
    node_count: int = 0
    edge_count: int = 0
    node_types: list[str] = Field(default_factory=list)
    edge_types: list[str] = Field(default_factory=list)


class MaterialsGraphData(BaseModel):
    source_title: str
    course_profile: MaterialsGraphCourseProfile
    nodes: list[MaterialsGraphNode]
    edges: list[MaterialsGraphEdge]
    stats: MaterialsGraphStats


class MaterialsGraphExtractRequest(BaseModel):
    source_title: str
    content: str
    project_id: str = "default"


class MaterialsGraphPageRequest(BaseModel):
    page_path: str
    project_id: str = "default"
