from pydantic import BaseModel


class ResearchRequest(BaseModel):
    page_path: str
    action: str
    note: str = ""


class ResearchResponse(BaseModel):
    action: str
    title: str
    content: str
    related_pages: list[dict] = []


class ResearchSaveRequest(BaseModel):
    page_path: str
    title: str
    content: str
