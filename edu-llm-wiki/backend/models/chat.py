
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


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    conversation_id: str = "default"
    context_budget: int = 32000  # max context in chars
    mode: str = "ask"  # ask | practice
    scope: ChatScope = Field(default_factory=ChatScope)
    options: ChatOptions = Field(default_factory=ChatOptions)


class CitedPage(BaseModel):
    path: str
    title: str
    snippet: str


class ChatResponse(BaseModel):
    content: str
    cited_pages: list[CitedPage] = []
    conversation_id: str = "default"


class Conversation(BaseModel):
    id: str
    title: str
    messages: list[ChatMessage]
    created: str
    updated: str
