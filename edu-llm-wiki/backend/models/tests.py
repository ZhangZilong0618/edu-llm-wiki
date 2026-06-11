from pydantic import BaseModel, Field


class TestCreateRequest(BaseModel):
    title: str | None = None
    scope: str = "wiki"
    source: str | None = None
    question_count: int = Field(default=5, ge=1, le=30)
    question_types: list[str] = ["multiple_choice", "fill_blank", "short_answer"]
    difficulty: str = "mixed"
    mode: str = "practice"
    # Caller-provided seed used to encourage question diversity between
    # consecutive generations. Frontend fills this with a timestamp/random
    # suffix; the backend echoes it into the prompt and may fall back to a
    # server-side UUID when missing.
    seed: str | None = None


class TestAnswerRequest(BaseModel):
    answers: dict[str, str | list[str]]


class TestQuestion(BaseModel):
    id: str
    type: str
    prompt: str
    options: list[str] = []
    blanks: int = 0
    answer: str | list[str] = ""
    explanation: str = ""
    related_page: str | None = None
    concepts: list[str] = []
    difficulty: str = "mixed"


class TestAttempt(BaseModel):
    question_id: str
    user_answer: str | list[str] = ""
    score: float = 0
    max_score: float = 1
    level: str = "empty"
    feedback: str = ""
    correct_answer: str | list[str] = ""
    # v3: per-attempt self-reported confidence 1..5; optional to stay
    # backwards-compatible with clients that don't yet render the slider.
    confidence: int | None = None
    # v3: LLM- or user-tagged misconception IDs, used by error_model.
    misconception_ids: list[str] | None = None


class TestSession(BaseModel):
    id: str
    title: str
    scope: str = "wiki"
    source: str | None = None
    mode: str = "practice"
    difficulty: str = "mixed"
    status: str = "active"
    questions: list[TestQuestion]
    attempts: list[TestAttempt] = []
    score: float | None = None
    max_score: float | None = None
    created_at: str
    submitted_at: str | None = None


class TestSummary(BaseModel):
    id: str
    title: str
    status: str
    question_count: int
    score: float | None = None
    max_score: float | None = None
    created_at: str
    submitted_at: str | None = None
