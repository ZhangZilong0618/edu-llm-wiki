
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: str  # user | assistant | system
    content: str


class ChatScope(BaseModel):
    type: str = "whole_wiki"  # whole_wiki | current_page | selected_source
    page_path: str | None = None
    source_name: str | None = None


class ChatOptions(BaseModel):
    citation_required: bool = True
    answer_style: str = "concise"  # concise | detailed | socratic
    # ``react`` runs the MCP-tool ReAct agent (the default). ``graph``/``vector``
    # /``none`` keep the legacy pipeline for ablations and integrations.
    retrieval_mode: Literal["none", "vector", "graph", "react"] = "react"
    include_learner_state: bool = True
    model: str | None = None
    # ``agent_mode`` is additive to the legacy top-level ``mode`` field. It
    # lets clients request a structured practice/review turn while retaining
    # the normal RAG answer flow for ``ask``.
    agent_mode: Literal["auto", "ask", "practice", "review"] = "auto"
    # Reference the latest completed conversational assessment. The server
    # resolves the question and grading details from its own records.
    assessment_context_question_id: str | None = None


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    conversation_id: str = "default"
    user_id: str = "default"
    context_budget: int = 32000  # max context in chars
    mode: str = "auto"  # auto | ask | practice | review
    scope: ChatScope = Field(default_factory=ChatScope)
    options: ChatOptions = Field(default_factory=ChatOptions)


class PracticeQuestionRequest(BaseModel):
    """Request one server-owned question for a chat practice turn."""

    session_id: str | None = None
    mode: Literal["practice", "review"] = "practice"
    page_path: str | None = None
    kc_id: str | None = None
    difficulty: str = "mixed"


class PracticeAnswerRequest(BaseModel):
    """Submit an answer without sending the expected answer/KC from the UI."""

    question_id: str
    answer: str | list[str] = ""
    confidence: int = Field(ge=1, le=5)
    hint_ladder: int = 0
    attempt_id: str = Field(default_factory=lambda: uuid4().hex)


class CitedPage(BaseModel):
    path: str
    title: str
    snippet: str
    # Optional slugified section heading; the chat UI scrolls the wiki page
    # to this anchor when the citation is clicked.
    anchor: str | None = None


class ChatResponse(BaseModel):
    content: str
    cited_pages: list[CitedPage] = []
    conversation_id: str = "default"
    # Structured tutoring payloads are optional so existing chat consumers
    # can continue to render ordinary answers unchanged.
    practice_question: dict | None = None
    evaluation: dict | None = None
    learning_update: dict | None = None


class Conversation(BaseModel):
    id: str
    title: str
    messages: list[ChatMessage]
    created: str
    updated: str
