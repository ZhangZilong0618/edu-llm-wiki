"""API routes for chat Q&A."""

import json
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from models.chat import ChatRequest, ChatResponse, ChatMessage, CitedPage
from services.llm_client import stream_chat
from services.search_engine import search

router = APIRouter(prefix="/api/chat", tags=["chat"])


SYSTEM_PROMPT = """You are an expert educational assistant with access to a knowledge base of course materials.

## Instructions
- Answer questions based on the provided wiki pages and your knowledge.
- When citing wiki pages, use the format: [{{number}}] where number corresponds to the page number in the context.
- Be precise and educational. Explain concepts clearly.
- If the wiki content doesn't fully answer the question, supplement with your knowledge but clearly distinguish.
- Use LaTeX for mathematical formulas: inline $...$ and block $$...$$.

## Wiki Context
{wiki_context}

## Purpose
{purpose}
"""


def _build_context(search_results: list[dict], max_chars: int = 20000) -> tuple[str, list[dict]]:
    """Build wiki context from search results with budget control."""
    context_parts = []
    cited = []
    chars_used = 0

    for i, r in enumerate(search_results):
        entry = f"[{i + 1}] **{r['title']}** ({r['path']})\n{r.get('snippet', '')}"
        if chars_used + len(entry) > max_chars:
            break
        context_parts.append(entry)
        chars_used += len(entry)
        cited.append({
            "path": r["path"],
            "title": r["title"],
            "snippet": r.get("snippet", "")[:100],
        })

    return "\n\n".join(context_parts), cited


@router.post("", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """Chat with the knowledge base. Non-streaming."""
    # Search for relevant context
    last_user_msg = ""
    for msg in reversed(req.messages):
        if msg.role == "user":
            last_user_msg = msg.content
            break

    search_results = await search(last_user_msg, top_k=10)
    wiki_context, cited = _build_context(search_results["results"], max_chars=20000)

    # Read purpose
    from storage.wiki_store import wiki_path
    purpose = (wiki_path() / "purpose.md").read_text(encoding="utf-8")[:2000] if (wiki_path() / "purpose.md").exists() else "Not defined"

    # Build messages
    system = SYSTEM_PROMPT.format(wiki_context=wiki_context, purpose=purpose)
    messages = [{"role": m.role, "content": m.content} for m in req.messages]

    # Get response
    from services.llm_client import chat_complete
    response = await chat_complete(system_prompt=system, messages=messages)

    return ChatResponse(
        content=response,
        cited_pages=[CitedPage(**c) for c in cited],
        conversation_id=req.conversation_id,
    )


@router.post("/stream")
async def chat_stream(req: ChatRequest):
    """Chat with the knowledge base. Streaming response."""
    last_user_msg = ""
    for msg in reversed(req.messages):
        if msg.role == "user":
            last_user_msg = msg.content
            break

    search_results = await search(last_user_msg, top_k=10)
    wiki_context, cited = _build_context(search_results["results"], max_chars=20000)

    from storage.wiki_store import wiki_path
    purpose = (wiki_path() / "purpose.md").read_text(encoding="utf-8")[:2000] if (wiki_path() / "purpose.md").exists() else "Not defined"

    system = SYSTEM_PROMPT.format(wiki_context=wiki_context, purpose=purpose)
    messages = [{"role": m.role, "content": m.content} for m in req.messages]

    async def generate():
        yield f"data: {json.dumps({'type': 'cited', 'pages': [{'path': c['path'], 'title': c['title'], 'snippet': c['snippet']} for c in cited]})}\n\n"
        async for chunk in stream_chat(system_prompt=system, messages=messages):
            yield f"data: {json.dumps({'type': 'content', 'text': chunk})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
