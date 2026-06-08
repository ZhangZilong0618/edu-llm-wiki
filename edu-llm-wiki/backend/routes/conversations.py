"""API routes for conversation history."""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from storage.wiki_store import (
    delete_conversation,
    get_conversation,
    list_conversations,
    save_conversation,
)

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


class SaveConversationRequest(BaseModel):
    id: str
    title: str = "Untitled"
    messages: list[dict] = []


@router.get("")
async def list_convs(project_id: str = Query("default")):
    """List all conversations for a project."""
    return list_conversations(project_id=project_id)


@router.get("/{conv_id}")
async def get_conv(conv_id: str, project_id: str = Query("default")):
    """Get a single conversation."""
    conv = get_conversation(conv_id, project_id=project_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv


@router.post("")
async def create_or_update_conv(req: SaveConversationRequest, project_id: str = Query("default")):
    """Create or update a conversation."""
    # auto-generate title from first user message if untitled
    title = req.title
    if title == "Untitled" and req.messages:
        for m in req.messages:
            if m.get("role") == "user":
                title = m["content"][:50]
                break
    conv = {
        "id": req.id,
        "title": title,
        "messages": req.messages,
    }
    save_conversation(conv, project_id=project_id)
    return {"status": "saved", "id": conv["id"]}


@router.delete("/{conv_id}")
async def delete_conv(conv_id: str, project_id: str = Query("default")):
    """Delete a conversation."""
    if delete_conversation(conv_id, project_id=project_id):
        return {"status": "deleted"}
    raise HTTPException(status_code=404, detail="Conversation not found")
