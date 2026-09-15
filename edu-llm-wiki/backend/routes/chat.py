"""API routes for chat Q&A with graph-enhanced RAG pipeline."""

import asyncio
import json
import re
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse

from config import settings
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

def _slugify(text: str) -> str:
    s = (text or "").strip().lower()
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"[^\w一-鿿-]+", "", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "section"


def _split_sections(content: str):
    if not content:
        return []
    pattern = re.compile(r"(?m)^(#{1,3})\s+(.+?)\s*#*\s*$")
    matches = list(pattern.finditer(content))
    sections = []
    cursor = 0
    for i, m in enumerate(matches):
        heading = m.group(2).strip()
        if cursor < m.start():
            sections.append(("", content[cursor:m.start()]))
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        sections.append((heading, content[start:end]))
        cursor = end
    if cursor < len(content):
        sections.append(("", content[cursor:]))
    return [(h, b) for h, b in sections if h or b.strip()]


def _best_anchor(query: str, content: str, fallback_heading: str = "") -> str:
    sections = _split_sections(content)
    if not sections:
        return _slugify(fallback_heading) if fallback_heading else ""
    qtoks = set()
    for i in range(len(query) - 1):
        bigram = query[i:i + 2]
        if all("\u4e00" <= c <= "\u9fff" for c in bigram):
            qtoks.add(bigram)
    for word in re.findall(r"[A-Za-z0-9]+", query.lower()):
        if len(word) >= 2:
            qtoks.add(word)
    best_heading = sections[0][0]
    best_score = -1
    for heading, body in sections:
        if not heading:
            continue
        body_lower = body.lower()
        score = 0
        for tok in qtoks:
            score += body_lower.count(tok)
        if score > best_score:
            best_score = score
            best_heading = heading
    if best_score <= 0:
        for heading, _ in sections:
            if heading:
                return _slugify(heading)
        return ""
    return _slugify(best_heading)


GREETING_PROMPT = """You are a wiki assistant. The user sent a casual greeting — reply briefly and naturally, in one or two sentences. Do NOT invent wiki content or pretend to have retrieved pages.

{language_instruction}
"""


def _require_admin_token(
    admin_token: str | None = Query(None, description="管理员令牌，与 Settings.api_token 匹配"),
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
) -> None:
    """Raise 401 unless the configured api_token matches the caller-provided one.

    When ``settings.api_token`` is empty (the local-dev default) the gate
    stays open so the chat works without configuration. Production deploys
    set the token via env and the same value into the localStorage key
    ``edu-llm-wiki.adminToken`` on the admin's browser.
    """
    expected = (getattr(settings, "api_token", "") or "").strip()
    if not expected:
        return
    provided = (admin_token or x_admin_token or "").strip()
    if provided != expected:
        raise HTTPException(status_code=401, detail="admin_token missing or invalid")


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
    admin_token: str | None = Query(None),
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
):
    """..."""
    _require_admin_token(admin_token, x_admin_token)
    del project_id  # Reserved for future per-project OCR history.
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
    on_status=None,
    abort_signal: "asyncio.Event | None" = None,
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

    async def emit_status(text: str) -> None:
        if on_status is None:
            return
        try:
            await on_status(text)
        except Exception:
            # Status is best-effort; never fail retrieval on a callback error.
            pass

    await emit_status("正在检索相关 Wiki 页面")

    graph_evidence = await collect_graph_evidence(
        query,
        top_results,
        budget,
        project_id=project_id,
        user_id=user_id,
        on_status=emit_status,
        abort_signal=abort_signal,
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
        # Attach a per-page section anchor so the frontend can jump to
        # the most relevant heading instead of the page top.
        for _, p in enumerate(relevant_pages):
            anchor = _best_anchor(query, p["content"], p["title"])
            cited.append({
                "path": p["path"],
                "title": p["title"],
                "snippet": p["content"][:200],
                "anchor": anchor,
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
async def chat(
    req: ChatRequest,
    project_id: str = Query("default"),
    admin_token: str | None = Query(None),
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
):
    """Chat with the knowledge base. Non-streaming."""
    _require_admin_token(admin_token, x_admin_token)
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
async def chat_stream(
    req: ChatRequest,
    request: Request,
    project_id: str = Query("default"),
    admin_token: str | None = Query(None),
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
):
    """Chat with the knowledge base. Streaming SSE response."""
    _require_admin_token(admin_token, x_admin_token)
    # Local abort flag — signalled as soon as the client disconnects so the
    # LLM stops generating instead of finishing a response the user has
    # already discarded.
    abort_event = asyncio.Event()
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

    # Full RAG pipeline with status relay so the user can see graph retrieval progress.
    budget = compute_budget(req.context_budget)
    status_queue: asyncio.Queue[str] = asyncio.Queue()

    async def on_status(text: str) -> None:
        try:
            await status_queue.put(text)
        except Exception:
            pass

    pipeline_task = asyncio.create_task(
        _run_rag_pipeline(
            last_user_msg,
            budget,
            project_id=project_id,
            user_id=req.user_id,
            scope=req.scope,
            on_status=on_status,
            abort_signal=abort_event,
        )
    )

    async def _watch_disconnect() -> None:
        try:
            while not abort_event.is_set():
                if await request.is_disconnected():
                    abort_event.set()
                    return
                await asyncio.sleep(0.25)
        except Exception:
            abort_event.set()

    async def generate():
        watcher = asyncio.create_task(_watch_disconnect())
        # While pipeline runs, relay any status updates immediately.
        while not pipeline_task.done():
            try:
                text = await asyncio.wait_for(status_queue.get(), timeout=0.1)
                yield f"data: {json.dumps({'type': 'status', 'stage': 'retrieve', 'text': text})}\n\n"
            except asyncio.TimeoutError:
                continue
        # Drain anything queued right at the end.
        while not status_queue.empty():
            text = status_queue.get_nowait()
            yield f"data: {json.dumps({'type': 'status', 'stage': 'retrieve', 'text': text})}\n\n"

        # If the pipeline raised, surface the error instead of leaving the
        # client waiting for a stream that will never produce [DONE].
        if pipeline_task.cancelled():
            yield f"data: {json.dumps({'type': 'error', 'message': '请求已取消'})}\n\n"
            yield "data: [DONE]\n\n"
            return
        exc = pipeline_task.exception()
        if exc is not None:
            detail = str(exc)[:240] or exc.__class__.__name__
            yield f"data: {json.dumps({'type': 'error', 'message': f'检索失败：{detail}'})}\n\n"
            yield "data: [DONE]\n\n"
            return

        pages_context, cited, page_list, index, purpose, learner_profile = pipeline_task.result()

        system = SYSTEM_PROMPT.format(
            mode_instruction=_mode_instruction(req.mode, req.options.answer_style),
            language_instruction=language_instruction(),
            learner_profile=learner_profile,
            purpose=purpose or "Not defined",
            index=index or "(No index)",
            page_list=page_list,
            pages_context=pages_context,
        )

        yield f"data: {json.dumps({'type': 'sources', 'pages': [{'path': c['path'], 'title': c['title'], 'snippet': c['snippet'], 'anchor': c.get('anchor')} for c in cited]})}\n\n"
        yield f"data: {json.dumps({'type': 'status', 'stage': 'answer', 'text': '正在生成带引用回答...'})}\n\n"
        full_response = ""
        try:
            try:
                async for chunk in stream_chat(
                    system_prompt=system,
                    messages=messages,
                    abort_signal=abort_event,
                ):
                    full_response += chunk
                    yield f"data: {json.dumps({'type': 'content', 'text': chunk})}\n\n"
            except asyncio.CancelledError:
                raise
            except Exception as e:
                # The LLM stream broke mid-flight; let the client see a clear
                # message and end cleanly so the UI can recover.
                detail = str(e)[:240] or e.__class__.__name__
                yield f"data: {json.dumps({'type': 'error', 'message': f'生成中断：{detail}'})}\n\n"
                yield "data: [DONE]\n\n"
                return
        finally:
            # Always signal the watcher to stop and wait for it to exit.
            abort_event.set()
            watcher.cancel()
        cleaned, actual_cited = _filter_actual_citations(full_response, cited)
        yield f"data: {json.dumps({'type': 'replace', 'text': cleaned})}\n\n"
        yield f"data: {json.dumps({'type': 'final_citations', 'pages': [{'path': c['path'], 'title': c['title'], 'snippet': c['snippet'], 'anchor': c.get('anchor')} for c in actual_cited]})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
