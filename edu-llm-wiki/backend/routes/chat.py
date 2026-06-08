"""API routes for chat Q&A with graph-enhanced RAG pipeline."""

import json
import re

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from models.chat import ChatRequest, ChatResponse, CitedPage
from services.context_budget import compute_budget
from services.ingest_engine import _strip_images
from services.llm_client import chat_complete, stream_chat
from services.search_engine import graph_expand, keyword_search
from storage.wiki_store import read_wiki_page, wiki_path

router = APIRouter(prefix="/api/chat", tags=["chat"])


# Simple greeting patterns for short-circuiting retrieval
GREETING_RE = re.compile(
    r'^(hi|hey|hello|yo|sup|你好|嗨|您好|早上好|晚上好|下午好|哈喽|在吗|在么|hello there|good morning|good evening|good afternoon)[\s!！。.,，~～]*$',
    re.IGNORECASE,
)


def _is_greeting(text: str) -> bool:
    """Check if the message is just a greeting — no retrieval needed."""
    t = text.strip()
    if GREETING_RE.match(t):
        return True
    # Only treat very short pure-greeting-sounding text as greeting
    lower = t.lower()
    if len(t) <= 3 and lower in {"hi", "hey", "yo", "哈", "嗨", "嗯", "啊", "哦", "?"}:
        return True
    return False


SYSTEM_PROMPT = """You are a knowledgeable wiki assistant. Answer questions based on the wiki content provided below.

## Rules
- Answer based ONLY on the numbered wiki pages provided below.
- If the provided pages don't contain enough information, say so honestly.
- Use [[wikilink]] syntax to reference wiki pages.
- When citing information, use the page number in brackets, e.g. [1], [2].
- Use LaTeX for mathematical formulas: inline $...$ and block $$...$$.
- At the VERY END of your response, add a hidden comment listing which page numbers you used:
  <!-- cited: 1, 3, 5 -->

## Wiki Purpose
{purpose}

## Wiki Index
{index}

## Page List
{page_list}

## Wiki Pages
{pages_context}
"""

GREETING_PROMPT = """You are a wiki assistant. The user sent a casual greeting — reply briefly and naturally, in one or two sentences. Do NOT invent wiki content or pretend to have retrieved pages."""


async def _run_rag_pipeline(
    query: str,
    budget: dict,
    *,
    project_id: str = "default",
) -> tuple[str, list[dict], str, str]:
    """Full RAG pipeline: search → vector → graph expand → budget fill → context assembly.

    Returns: (pages_context, cited, page_list, index)
    """
    wp = wiki_path(project_id)
    PAGE_BUDGET = budget["page_budget"]
    MAX_PAGE_SIZE = budget["max_page_size"]
    INDEX_BUDGET = budget["index_budget"]

    # ── Read purpose and index ──
    purpose = ""
    purpose_path = wp / "purpose.md"
    if purpose_path.exists():
        purpose = _strip_images(purpose_path.read_text(encoding="utf-8"))[:2000]

    raw_index = ""
    index_path = wp / "index.md"
    if index_path.exists():
        raw_index = _strip_images(index_path.read_text(encoding="utf-8"))

    # ── Phase 1: Vector semantic search (primary) ──
    top_results: list[dict] = []
    try:
        from services.vector_store import vector_search
        vector_results = vector_search(query, top_k=20, project_id=project_id)
        for i, vr in enumerate(vector_results):
            top_results.append({
                "path": vr["path"],
                "title": vr["title"],
                "snippet": vr["snippet"],
                "score": 15.0 - i * 0.5,  # rank-weighted base score
                "title_match": False,
                "vector_score": vr["score"],
            })
    except Exception as e:
        print(f"[RAG] Vector search unavailable: {e}")

    # ── Phase 1.5: Keyword search (fallback / supplementary) ──
    keyword_results = keyword_search(query, top_k=10, project_id=project_id)
    keyword_paths = {r["path"] for r in top_results}
    for kr in keyword_results:
        if kr["path"] not in keyword_paths:
            kr["score"] = max(1, kr["score"] * 0.7)  # lower priority than vector results
            top_results.append(kr)
    # Boost vector hits that also show in keyword
    for r in top_results:
        if r["path"] in {k["path"] for k in keyword_results}:
            r["score"] += 2.0

    top_results.sort(key=lambda x: -x["score"])
    top_results = top_results[:20]

    # ── Phase 2: Graph 1-hop expansion with relevance threshold ──
    try:
        expanded = await graph_expand(top_results, depth=1, project_id=project_id)
        # expanded already merged and sorted by score
        top_results = expanded[:20]
    except Exception:
        pass

    # ── Trim index to relevant entries ──
    index = raw_index
    if len(raw_index) > INDEX_BUDGET:
        from services.search_engine import tokenize_query
        tokens = set(tokenize_query(query))
        lines = raw_index.split("\n")
        kept_lines: list[str] = []
        kept_size = 0
        for line in lines:
            is_header = line.startswith("##")
            lower = line.lower()
            is_relevant = any(t in lower for t in tokens)
            if (is_header or is_relevant) and kept_size + len(line) + 1 <= INDEX_BUDGET:
                kept_lines.append(line)
                kept_size += len(line) + 1
        index = "\n".join(kept_lines)
        if len(index) < len(raw_index):
            index += "\n\n[...index trimmed to relevant entries...]"

    # ── Phase 3: Priority-based page filling ──
    used_chars = 0
    relevant_pages: list[dict] = []

    async def try_add_page(title: str, file_path: str, priority: int) -> bool:
        nonlocal used_chars
        if used_chars >= PAGE_BUDGET:
            return False
        try:
            page = read_wiki_page(file_path, project_id=project_id)
            if not page:
                return False
            content = _strip_images(page.get("content", ""))
            if len(content) > MAX_PAGE_SIZE:
                content = content[:MAX_PAGE_SIZE] + "\n\n[...truncated...]"
            if used_chars + len(content) > PAGE_BUDGET:
                return False
            used_chars += len(content)
            relevant_pages.append({
                "title": title,
                "path": file_path,
                "content": content,
                "priority": priority,
            })
            return True
        except Exception:
            return False

    # P0: Title matches (highest priority)
    for r in top_results:
        if r.get("title_match"):
            await try_add_page(r["title"], r["path"], 0)

    # P1: Content matches (medium priority)
    for r in top_results:
        if not r.get("title_match"):
            await try_add_page(r["title"], r["path"], 1)

    # P2: Graph-expanded nodes (lower priority)
    for r in top_results:
        if r.get("score", 0) < 3.0 and not r.get("title_match"):
            await try_add_page(r["title"], r["path"], 2)

    # ── Assemble context ──
    pages_context = ""
    page_list = ""
    cited: list[dict] = []

    if relevant_pages:
        pages_context = "\n\n---\n\n".join(
            f"### [{i + 1}] {p['title']}\nPath: {p['path']}\n\n{p['content']}"
            for i, p in enumerate(relevant_pages)
        )
        page_list = "\n".join(
            f"[{i + 1}] {p['title']} ({p['path']})"
            for i, p in enumerate(relevant_pages)
        )
        for _, p in enumerate(relevant_pages):
            cited.append({
                "path": p["path"],
                "title": p["title"],
                "snippet": p["content"][:200],
            })
    else:
        pages_context = "(No relevant wiki pages found)"
        page_list = "(No pages matched)"

    return pages_context, cited, page_list, index, purpose


@router.post("", response_model=ChatResponse)
async def chat(req: ChatRequest, project_id: str = Query("default")):
    """Chat with the knowledge base. Non-streaming."""
    last_user_msg = ""
    for msg in reversed(req.messages):
        if msg.role == "user":
            last_user_msg = msg.content
            break

    messages = [{"role": m.role, "content": m.content} for m in req.messages]

    # Greeting short-circuit
    if _is_greeting(last_user_msg):
        response = await chat_complete(
            system_prompt=GREETING_PROMPT,
            messages=messages,
        )
        return ChatResponse(content=response, cited_pages=[], conversation_id=req.conversation_id)

    # Full RAG pipeline
    budget = compute_budget(None)
    pages_context, cited, page_list, index, purpose = await _run_rag_pipeline(
        last_user_msg, budget, project_id=project_id,
    )

    system = SYSTEM_PROMPT.format(
        purpose=purpose or "Not defined",
        index=index or "(No index)",
        page_list=page_list,
        pages_context=pages_context,
    )

    response = await chat_complete(system_prompt=system, messages=messages)

    return ChatResponse(
        content=response,
        cited_pages=[CitedPage(**c) for c in cited],
        conversation_id=req.conversation_id,
    )


@router.post("/stream")
async def chat_stream(req: ChatRequest, project_id: str = Query("default")):
    """Chat with the knowledge base. Streaming SSE response."""
    last_user_msg = ""
    for msg in reversed(req.messages):
        if msg.role == "user":
            last_user_msg = msg.content
            break

    messages = [{"role": m.role, "content": m.content} for m in req.messages]

    # Greeting short-circuit
    if _is_greeting(last_user_msg):
        async def greeting_gen():
            yield f"data: {json.dumps({'type': 'cited', 'pages': []})}\n\n"
            async for chunk in stream_chat(system_prompt=GREETING_PROMPT, messages=messages):
                yield f"data: {json.dumps({'type': 'content', 'text': chunk})}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(greeting_gen(), media_type="text/event-stream")

    # Full RAG pipeline
    budget = compute_budget(None)
    pages_context, cited, page_list, index, purpose = await _run_rag_pipeline(
        last_user_msg, budget, project_id=project_id,
    )

    system = SYSTEM_PROMPT.format(
        purpose=purpose or "Not defined",
        index=index or "(No index)",
        page_list=page_list,
        pages_context=pages_context,
    )

    async def generate():
        yield f"data: {json.dumps({'type': 'cited', 'pages': [{'path': c['path'], 'title': c['title'], 'snippet': c['snippet']} for c in cited]})}\n\n"
        async for chunk in stream_chat(system_prompt=system, messages=messages):
            yield f"data: {json.dumps({'type': 'content', 'text': chunk})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
