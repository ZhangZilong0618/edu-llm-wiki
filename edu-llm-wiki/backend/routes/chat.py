"""API routes for chat Q&A with graph-enhanced RAG pipeline."""

import asyncio
import json
import re
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse

from models.chat import ChatRequest, ChatResponse, ChatScope, CitedPage
from services.context_budget import compute_budget
from services.ingest_engine import _strip_images
from services.graph_qa import collect_graph_evidence
from services.language import language_instruction
from services.llm_client import chat_complete, stream_chat
from services.search_engine import keyword_search
from storage.wiki_store import list_wiki_pages, read_wiki_page, wiki_path

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


SYSTEM_PROMPT = r"""You are a knowledgeable wiki assistant. Answer questions based on the wiki content provided below.

## Interaction Mode
{mode_instruction}

## Output Language
{language_instruction}

## Rules
- Answer based ONLY on the numbered wiki pages provided below.
- If the provided pages don't contain enough information, say so honestly.
- Use [[wikilink]] syntax to reference wiki pages.
- When citing information, use the page number in brackets, e.g. [1], [2].
- Use LaTeX for mathematical formulas: inline $...$ and block $$...$$. Never write bare LaTeX commands like \sigma or \varepsilon without $...$ delimiters.
- At the VERY END of your response, add a hidden comment listing which page numbers you used:
  <!-- cited: 1, 3, 5 -->

## Learner Profile
{learner_profile}

## Wiki Purpose
{purpose}

## Wiki Index
{index}

## Page List
{page_list}

## Wiki Pages
{pages_context}
"""

GREETING_PROMPT = """You are a wiki assistant. The user sent a casual greeting — reply briefly and naturally, in one or two sentences. Do NOT invent wiki content or pretend to have retrieved pages.

{language_instruction}
"""


def _mode_instruction(mode: str, answer_style: str) -> str:
    if mode == "practice":
        return (
            "You are a patient learning coach. If the user is answering a question, diagnose their answer, "
            "give one targeted hint before a full solution, and connect feedback to the cited wiki pages."
        )
    if answer_style == "detailed":
        return "Give a structured, detailed explanation with examples when useful."
    if answer_style == "socratic":
        return "Guide the user with short Socratic steps and avoid jumping straight to the final answer."
    return "Answer directly and concisely, with enough explanation to be useful."


def _extract_cited_numbers(response: str) -> tuple[str, set[int]]:
    match = re.search(r"<!--\s*cited:\s*([0-9,\s]+)\s*-->", response, re.IGNORECASE)
    if not match:
        return response.strip(), set()
    numbers = {int(n) for n in re.findall(r"\d+", match.group(1))}
    cleaned = (response[:match.start()] + response[match.end():]).strip()
    return cleaned, numbers


def _filter_actual_citations(response: str, cited: list[dict]) -> tuple[str, list[dict]]:
    cleaned, numbers = _extract_cited_numbers(response)
    if numbers:
        return cleaned, [c for i, c in enumerate(cited, start=1) if i in numbers]
    bracket_numbers = {int(n) for n in re.findall(r"\[(\d+)\]", cleaned)}
    if bracket_numbers:
        return cleaned, [c for i, c in enumerate(cited, start=1) if i in bracket_numbers]
    return cleaned, []


@router.post("/image-ocr")
async def image_ocr(
    file: UploadFile = File(...),
    project_id: str = Query("default"),
):
    """Extract question text from an uploaded/captured image for chat input.

    Uses PaddleOCR-VL instead of the chat LLM, so text-only LLMs such as
    DeepSeek can still answer after OCR converts the photo to text.
    """
    del project_id  # Reserved for future per-project OCR history.
    content_type = file.content_type or ""
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Please upload an image file.")

    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Empty image.")
    if len(image_bytes) > 12 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Image is too large. Please upload an image under 12MB.")

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}:
        suffix = ".png"

    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(image_bytes)
            temp_path = Path(tmp.name)
        from services.paddleocr import parse_file_to_markdown
        text = await parse_file_to_markdown(temp_path)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Image recognition failed: {str(e)[:240]}") from e
    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink(missing_ok=True)

    return {
        "filename": file.filename or "photo",
        "content_type": content_type,
        "text": text.strip(),
    }


def _scope_seed_results(scope: ChatScope, *, project_id: str = "default") -> list[dict]:
    if scope.type == "current_page" and scope.page_path:
        page = read_wiki_page(scope.page_path, project_id=project_id)
        if page:
            return [{
                "path": page["path"],
                "title": page["title"],
                "snippet": page.get("content", "")[:200],
                "score": 100.0,
                "title_match": True,
                "vector_score": None,
            }]
    if scope.type == "selected_source" and scope.source_name:
        seeded: list[dict] = []
        for summary in list_wiki_pages(project_id=project_id):
            page = read_wiki_page(summary["path"], project_id=project_id)
            if not page:
                continue
            source_names = page.get("sources", []) or []
            if scope.source_name in source_names or scope.source_name in page.get("title", "") or scope.source_name in page.get("path", ""):
                seeded.append({
                    "path": page["path"],
                    "title": page["title"],
                    "snippet": page.get("content", "")[:200],
                    "score": 90.0 - len(seeded),
                    "title_match": True,
                    "vector_score": None,
                })
            if len(seeded) >= 8:
                break
        return seeded
    return []


def _relation_context_for_pages(pages: list[dict], relations: list[dict]) -> str:
    """Render followed graph edges as numbered relation evidence for the LLM."""
    if not pages or not relations:
        return ""

    page_number = {p["path"]: i for i, p in enumerate(pages, 1)}
    node_to_path = {p.get("node_id", ""): p["path"] for p in pages if p.get("node_id")}
    lines: list[str] = []
    for edge in relations:
        source_path = node_to_path.get(edge.get("source", ""), edge.get("source", ""))
        target_path = node_to_path.get(edge.get("target", ""), edge.get("target", ""))
        if source_path not in page_number or target_path not in page_number:
            continue
        evidence = edge.get("evidence") or edge.get("rationale") or ""
        line = (
            f"[{page_number[source_path]}] --{edge.get('edge_type', 'related')}--> "
            f"[{page_number[target_path]}]"
        )
        if evidence:
            compact = re.sub(r"\s+", " ", evidence).strip()
            line += f": {compact[:300]}"
        lines.append(line)

    if not lines:
        return ""
    return "\n\n## Followed graph relations\n" + "\n".join(lines[:40])


def _format_learner_profile(project_id: str, user_id: str) -> str:
    """Format a compact, privacy-safe learner profile for the tutor prompt."""
    try:
        from services.mastery import learner_state_summary
        state = learner_state_summary(project_id=project_id, user_id=user_id)
    except Exception:
        return "No learner state available yet."

    weak = ", ".join(
        f"{item.get('title', item.get('kc_id'))} ({float(item.get('p_known', 0)):.2f})"
        for item in (state.get("weak_kcs") or [])[:5]
    ) or "none recorded"
    misconceptions = ", ".join(
        f"{item.get('label', item.get('tag'))} x{item.get('count', 0)}"
        for item in (state.get("misconception_clusters") or [])[:3]
    ) or "none recorded"
    due = int(state.get("sr_due_today", 0) or 0)
    overconfidence = float(state.get("overconfidence_gap", 0) or 0)
    readiness = float(state.get("readiness", 0) or 0)

    return (
        f"- average mastery: {float(state.get('p_known_avg', 0) or 0):.2f}\n"
        f"- weak knowledge components: {weak}\n"
        f"- recurring misconception patterns: {misconceptions}\n"
        f"- due review items: {due}\n"
        f"- overconfidence gap: {overconfidence:.2f}\n"
        f"- prerequisite readiness: {readiness:.2f}\n"
        "Use this profile to choose explanation depth and targeted feedback, but do not "
        "invent additional learner data."
    )


async def _run_rag_pipeline(
    query: str,
    budget: dict,
    *,
    project_id: str = "default",
    user_id: str = "default",
    scope: ChatScope | None = None,
) -> tuple[str, list[dict], str, str, str, str]:
    """Full RAG pipeline: scope/vector/keyword seeds → iterative graph evidence → context assembly.

    Returns: (pages_context, cited, page_list, index, purpose, learner_profile)
    """
    wp = wiki_path(project_id)
    INDEX_BUDGET = budget["index_budget"]
    index = ""

    # ── Read purpose and index ──
    purpose = ""
    purpose_path = wp / "purpose.md"
    if purpose_path.exists():
        purpose = _strip_images(purpose_path.read_text(encoding="utf-8"))[:2000]

    raw_index = ""
    index_path = wp / "index.md"
    if index_path.exists():
        raw_index = _strip_images(index_path.read_text(encoding="utf-8"))

    # ── Phase 0: Explicit user-selected scope ──
    top_results: list[dict] = _scope_seed_results(scope or ChatScope(), project_id=project_id)
    seeded_paths = {r["path"] for r in top_results}

    # ── Phase 1: Vector semantic search (primary) ──
    try:
        from services.vector_store import vector_search
        vector_results = await asyncio.to_thread(
            vector_search, query, top_k=20, project_id=project_id
        )
        for i, vr in enumerate(vector_results):
            if vr["path"] in seeded_paths:
                continue
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

    # ── Phase 2: Iterative graph-guided evidence collection ──
    # Search provides seed nodes; the controller traverses typed graph edges,
    # reads adjacent page content, and asks the LLM whether evidence covers the
    # question. It can therefore add prerequisite/mechanism pages that lexical
    # search alone would miss.
    graph_evidence = await collect_graph_evidence(
        query,
        top_results,
        budget,
        project_id=project_id,
        user_id=user_id,
    )
    relevant_pages = graph_evidence.pages

    # ── Assemble context ──
    pages_context = ""
    page_list = ""
    cited: list[dict] = []

    if relevant_pages:
        pages_context = "\n\n---\n\n".join(
            f"### [{i + 1}] {p['title']}\nPath: {p['path']}\n\n{p['content']}"
            for i, p in enumerate(relevant_pages)
        )
        relation_context = _relation_context_for_pages(relevant_pages, graph_evidence.relations)
        if relation_context:
            pages_context += relation_context
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

    # Record actual page exposures after the budget filter. This is stronger
    # evidence than a search impression: these pages were placed in the LLM
    # context for this learner.
    try:
        from services.graph_store import make_node_id, record_exposure
        for p in relevant_pages:
            record_exposure(
                project_id=project_id,
                user_id=user_id,
                node_id=make_node_id(project_id, p["path"]),
            )
    except Exception:
        pass

    learner_profile = await asyncio.to_thread(
        _format_learner_profile, project_id, user_id
    )
    return pages_context, cited, page_list, index, purpose, learner_profile


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
            system_prompt=GREETING_PROMPT.format(language_instruction=language_instruction()),
            messages=messages,
        )
        return ChatResponse(content=response, cited_pages=[], conversation_id=req.conversation_id)

    # Full RAG pipeline
    budget = compute_budget(req.context_budget)
    pages_context, cited, page_list, index, purpose, learner_profile = await _run_rag_pipeline(
        last_user_msg,
        budget,
        project_id=project_id,
        user_id=req.user_id,
        scope=req.scope,
    )

    system = SYSTEM_PROMPT.format(
        mode_instruction=_mode_instruction(req.mode, req.options.answer_style),
        language_instruction=language_instruction(),
        learner_profile=learner_profile,
        purpose=purpose or "Not defined",
        index=index or "(No index)",
        page_list=page_list,
        pages_context=pages_context,
    )

    response = await chat_complete(system_prompt=system, messages=messages)
    response, actual_cited = _filter_actual_citations(response, cited)

    return ChatResponse(
        content=response,
        cited_pages=[CitedPage(**c) for c in actual_cited],
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
            async for chunk in stream_chat(
                system_prompt=GREETING_PROMPT.format(language_instruction=language_instruction()),
                messages=messages,
            ):
                yield f"data: {json.dumps({'type': 'content', 'text': chunk})}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(greeting_gen(), media_type="text/event-stream")

    # Full RAG pipeline
    budget = compute_budget(req.context_budget)
    pages_context, cited, page_list, index, purpose, learner_profile = await _run_rag_pipeline(
        last_user_msg,
        budget,
        project_id=project_id,
        user_id=req.user_id,
        scope=req.scope,
    )

    system = SYSTEM_PROMPT.format(
        mode_instruction=_mode_instruction(req.mode, req.options.answer_style),
        language_instruction=language_instruction(),
        learner_profile=learner_profile,
        purpose=purpose or "Not defined",
        index=index or "(No index)",
        page_list=page_list,
        pages_context=pages_context,
    )

    async def generate():
        yield f"data: {json.dumps({'type': 'status', 'stage': 'retrieve', 'text': 'Reading relevant wiki pages...'})}\n\n"
        yield f"data: {json.dumps({'type': 'sources', 'pages': [{'path': c['path'], 'title': c['title'], 'snippet': c['snippet']} for c in cited]})}\n\n"
        yield f"data: {json.dumps({'type': 'status', 'stage': 'answer', 'text': 'Answering with citations...'})}\n\n"
        full_response = ""
        async for chunk in stream_chat(system_prompt=system, messages=messages):
            full_response += chunk
            yield f"data: {json.dumps({'type': 'content', 'text': chunk})}\n\n"
        cleaned, actual_cited = _filter_actual_citations(full_response, cited)
        yield f"data: {json.dumps({'type': 'replace', 'text': cleaned})}\n\n"
        yield f"data: {json.dumps({'type': 'final_citations', 'pages': [{'path': c['path'], 'title': c['title'], 'snippet': c['snippet']} for c in actual_cited]})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
