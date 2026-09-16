from pydantic import BaseModel, Field


class TestCreateRequest(BaseModel):
    title: str | None = None
    scope: str = "wiki"
    source: str | None = None
    # Free-form teacher/learner instruction, e.g. “出10道关于疲劳断裂的
    # 应用题，只要选择题和简答题”. The backend parses concrete constraints
    # and passes the full instruction to the generator.
    natural_prompt: str | None = None
    # Optional user-defined folder such as “期末复习/第二章”. Tests can be
    # moved between folders after generation.
    folder: str | None = None
    # Optional page-scoped generation. When present, context is restricted to
    # this wiki page instead of the whole project.
    page_path: str | None = None
    question_count: int = Field(default=5, ge=1, le=30)
    question_types: list[str] = ["multiple_choice", "fill_blank", "short_answer"]
    difficulty: str = "mixed"
    mode: str = "practice"
    # Caller-provided seed used to encourage question diversity between
    # consecutive generations. Frontend fills this with a timestamp/random
    # suffix; the backend echoes it into the prompt and may fall back to a
    # server-side UUID when missing.
    seed: str | None = None


class TestUpdateRequest(BaseModel):
    title: str | None = None
    folder: str | None = None


class TestAnswerRequest(BaseModel):
    answers: dict[str, str | list[str]]
    # Optional per-question confidence ratings (1..5) used by the calibration
    # observer. Missing questions are treated as no self-rating.
    confidences: dict[str, int] = Field(default_factory=dict)


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
    folder: str | None = None
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
    folder: str | None = None
    status: str
    question_count: int
    score: float | None = None
    max_score: float | None = None
    # Number of questions in this session that the learner got wrong. The
    # frontend sidebar uses this exact value instead of approximating it
    # from the (score / max_score) ratio, which would round wrong for any
    # partial-credit scoring.
    wrong_count: int | None = None
    created_at: str
    submitted_at: str | None = None
