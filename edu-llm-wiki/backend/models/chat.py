
from pydantic import BaseModel


class ChatMessage(BaseModel):
    role: str  # user | assistant | system
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    conversation_id: str = "default"
    context_budget: int = 32000  # max context in chars


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
