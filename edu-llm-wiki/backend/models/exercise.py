from pydantic import BaseModel, Field


class ExerciseCheckRequest(BaseModel):
    question: str
    student_answer: str
    reference_answer: str | None = None
    page_title: str | None = None
    page_path: str | None = None
    context: str | None = None


class ExerciseCheckResponse(BaseModel):
    level: str = Field(pattern="^(empty|weak|partial|good)$")
    title: str
    detail: str
    matched: list[str] = []
    missing: list[str] = []
    evidence: list[str] = []
    suggested_answer: str | None = None
    source: str = "ai"


class ExerciseCompleteSolutionRequest(BaseModel):
    page_path: str
    note: str | None = None


class ExerciseCompleteSolutionResponse(BaseModel):
    status: str
    solution: str
    page: dict
