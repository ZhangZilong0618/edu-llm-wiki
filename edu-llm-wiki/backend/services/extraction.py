"""知识单元抽取 —— 导入管线第一阶段(v2 重写)。

单一事实来源是 services/ontology_v2.py:抽取 prompt 的类型定义与判定
标准直接从本体的类描述(CLASS_LABELS)渲染——本体描述更新即抽取标准
更新,prompt 里不再维护第二份类型定义。

流程:长文档按页分块并发抽取 → 确定性合并去重;短文档(≤8 页且
≤24k 字符)全文单次抽取(超长截断)。产出 core_plan::

    {summary, tags, concepts, facts, formulas, principles,
     page_count_estimate, planning_source}

供下游阶段(页面生成/组装/写入)消费——下游只认这个形状,不感知本
模块的内部结构。

本模块同时承载通用 LLM-JSON 解析(repair_json / load_llm_json)与
分块工具,ingest_engine 复用。_strip_images 与 _clean_item_title 仍
住在 ingest_engine,此处函数级惰性导入以避免循环依赖(方向:
ingest_engine → extraction,运行时才反向取工具)。
"""

from __future__ import annotations

import asyncio
import json
import re

from services.language import language_instruction
from services.llm_client import chat_complete
from services.ontology_v2 import CLASS_LABELS

# A document import must have a bounded failure mode.  The normal chat client
# allows a much longer network timeout because interactive answers can stream,
# but a stalled model must never leave the ingest SSE request open indefinitely.
# Keep this local constant so deployments do not need a new configuration key
# just to get a safe fallback; callers/tests can still monkeypatch it.
LLM_EXTRACTION_TIMEOUT_SECONDS = 15.0

#: 四类知识单元的抽取顺序(与前端 PAGE_TYPE_ORDER 对齐)
KNOWLEDGE_UNIT_CLASSES = ("Concept", "Fact", "Formula", "Principle")

#: 每类的抽取输出字段(prompt schema 用,plain JSON 文本)
_EXTRACT_FIELDS: dict[str, str] = {
    "Concept": '{"name": "概念名(2-8字)", "definition": "一句话定义", '
               '"related": ["本片段其他概念名"], "page_refs": [1]}',
    "Fact": '{"name": "事实名(2-8字)", "statement": "单点具体陈述(常数/'
            '具体物质数据/约定阈值)", "page_refs": [1]}',
    "Formula": '{"name": "人类可读公式名(不是原始等式)", "latex": "LaTeX", '
               '"variables": "各变量含义", "applications": "何时使用", "page_refs": [1]}',
    "Principle": '{"name": "原理名", "statement": "一句话核心论断", '
                 '"conditions": "适用条件", "page_refs": [1]}',
}


# =========================================================================
# 本体驱动的 prompt 组装
# =========================================================================

def render_type_definitions() -> str:
    """从本体类描述(CLASS_LABELS)渲染抽取 prompt 的类型定义段。

    本体描述是抽取判定的单一事实来源——这里不做任何改写。
    """
    parts = []
    for cls_name in KNOWLEDGE_UNIT_CLASSES:
        zh, description = CLASS_LABELS[cls_name]
        parts.append(f"### {cls_name} {zh}\n{description}")
    return "\n\n".join(parts)


def render_output_schema() -> str:
    """渲染输出 JSON schema 段(逐类的字段规格)。"""
    lines = [
        "{",
        '  "chunk_summary": "2 句话概括本片段",',
        '  "topic_tags": ["3-6 个标签"],',
    ]
    items = list(_EXTRACT_FIELDS.items())
    for i, (cls_name, fields) in enumerate(items):
        plural = cls_name.lower() + "s"
        lines.append(f'  "{plural}": [')
        lines.append(f"    {fields}")
        lines.append("  ]" + ("," if i < len(items) - 1 else ""))
    lines.append("}")
    return "\n".join(lines)


EXTRACT_PROMPT = """You are an expert educational knowledge extractor. 从文档片段中抽取知识单元,逐个原子对照下方类型定义判定,边界条款优先于直觉。

## 知识单元类型定义(来自本体)
{type_definitions}

## 来源文档
- title: {source_title}
- 本片段页码范围: {page_range}

## 文档内容
{content}

## 输出 JSON schema
{output_schema}

规则:
- page_refs 只用本片段实际出现的页码;不确定则省略该字段。
- 每类抽取数量按片段实际内容调整,典型量级:4-10 概念、2-6 事实、0-3 公式、2-6 原理。
- 宁缺毋滥:边界模糊的原子按类型定义里的判定测试裁决,而不是猜测。
- 只输出一个 JSON 对象:无 markdown 围栏、无解释。

## 输出语言
{language_instruction}
"""


# =========================================================================
# LLM-JSON 解析(通用工具,ingest_engine 复用)
# =========================================================================

def repair_json(text: str) -> str:
    """Repair malformed JSON from LLM output — markdown fences, trailing text, truncation."""
    # 1. Strip markdown code fences
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[1] if len(parts) > 1 else text
        if text.startswith("json"):
            text = text[4:]

    # 2. Find the outermost JSON object/array by tracking brace depth
    # This handles LLMs that add explanatory text after the JSON
    json_start = -1
    json_end = -1
    depth = 0
    in_string = False
    escape_next = False
    opener = None

    for i, ch in enumerate(text):
        if escape_next:
            escape_next = False
            continue
        if ch == "\\" and in_string:
            escape_next = True
            continue
        if ch == '"' and not in_string:
            in_string = True
            if json_start < 0:
                json_start = i  # might be start of a string, reset below
            continue
        if ch == '"' and in_string:
            in_string = False
            continue
        if in_string:
            continue
        if ch in "{[" and depth == 0:
            json_start = i
            opener = ch
            depth += 1
            continue
        if ch in "{[" and depth > 0:
            depth += 1
            continue
        if (ch == "}" and opener == "{") or (ch == "]" and opener == "["):
            depth -= 1
            if depth == 0:
                json_end = i + 1
                break

    if json_start >= 0 and json_end > json_start:
        text = text[json_start:json_end]

    # 3. Remove trailing commas before closing brackets/braces
    text = re.sub(r",\s*([}\]])", r"\1", text)

    # 4. Close unterminated strings
    if text.count('"') % 2 != 0:
        text += '"'

    # 5. Close unclosed brackets/braces in reverse order (stack-based)
    stack: list[str] = []
    in_str = False
    esc = False
    for ch in text:
        if esc:
            esc = False
            continue
        if ch == "\\" and in_str:
            esc = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch in "{[":
            stack.append(ch)
        elif ch in "}]":
            if stack and ((ch == "}" and stack[-1] == "{") or (ch == "]" and stack[-1] == "[")):
                stack.pop()
    for opener in reversed(stack):
        text += "}" if opener == "{" else "]"

    # 6. Replace invalid JSON values that LLMs sometimes emit
    text = re.sub(r':\s*NaN\b', ': null', text)
    text = re.sub(r':\s*Infinity\b', ': null', text)
    text = re.sub(r':\s*-Infinity\b', ': null', text)

    return text


async def load_llm_json(raw: str, *, expected: str) -> object:
    """Parse LLM JSON output, asking the LLM to repair malformed JSON once if needed."""
    repaired = repair_json(raw)
    try:
        return json.loads(repaired)
    except json.JSONDecodeError as first_error:
        try:
            fixed = await asyncio.wait_for(
                chat_complete(
                    system_prompt=(
                        "You repair malformed JSON. Return ONLY valid JSON. "
                        "Do not add markdown fences, comments, explanations, or new content."
                    ),
                    messages=[{
                        "role": "user",
                        "content": (
                            f"The following should be a valid JSON {expected}, but parsing failed with:\n"
                            f"{first_error}\n\n"
                            "Repair syntax only. Preserve all keys, values, language, and structure as much as possible.\n\n"
                            f"{repaired[:60000]}"
                        ),
                    }],
                    temperature=0,
                    max_tokens=8192,
                ),
                timeout=LLM_EXTRACTION_TIMEOUT_SECONDS,
            )
        except (asyncio.TimeoutError, TimeoutError):
            return None
        except Exception:
            return None
        try:
            return json.loads(repair_json(fixed))
        except json.JSONDecodeError as second_error:
            raise ValueError(f"LLM returned malformed JSON and auto-repair failed: {second_error}") from second_error


# =========================================================================
# 分块(通用工具,ingest_engine 复用)
# =========================================================================

def build_page_chunks(
    content: str,
    *,
    source_title: str,
    project_id: str = "default",
    max_chars: int = 18_000,
    max_pages: int = 18,
) -> list[dict] | None:
    """Build page-aware chunks from parsed.json when available."""
    from services.ingest_engine import _strip_images  # 惰性导入避免循环依赖
    from services.parsed_index import build_parsed_index, load_parsed_index
    from storage.wiki_store import sources_path

    sources_root = sources_path(project_id)
    parsed = load_parsed_index(sources_root, source_title)
    if parsed is None:
        try:
            parsed = build_parsed_index(sources_root, source_title)
        except Exception:
            parsed = None
    if not parsed or not parsed.get("pages"):
        return None

    pages = parsed["pages"]
    if len(pages) <= 8 and len(content) <= 24_000:
        return None

    chunks: list[dict] = []
    current_pages: list[dict] = []
    current_chars = 0

    def flush() -> None:
        nonlocal current_pages, current_chars
        if not current_pages:
            return
        chunks.append({
            "start_page": int(current_pages[0].get("page", 1)),
            "end_page": int(current_pages[-1].get("page", len(current_pages))),
            "content": "\n\n---\n\n".join(
                f"## Page {page.get('page', idx + 1)}\n\n{_strip_images(str(page.get('md') or ''))}"
                for idx, page in enumerate(current_pages)
            ),
        })
        current_pages = []
        current_chars = 0

    for page in pages:
        text = _strip_images(str(page.get("md") or ""))
        if current_pages and (
            current_chars + len(text) > max_chars or len(current_pages) >= max_pages
        ):
            flush()
        current_pages.append(page)
        current_chars += len(text)

    flush()
    return chunks or None


# =========================================================================
# 抽取本体
# =========================================================================

async def extract_chunk(content: str, *, source_title: str, page_range: str) -> dict:
    """对一个文档片段执行 LLM 抽取,返回该片段的四类原子。"""
    prompt = EXTRACT_PROMPT.format(
        type_definitions=render_type_definitions(),
        source_title=source_title,
        page_range=page_range,
        content=content,
        output_schema=render_output_schema(),
        language_instruction=language_instruction(),
    )
    try:
        raw = await asyncio.wait_for(
            chat_complete(
                system_prompt="You are an expert educational knowledge extractor. Output ONLY valid JSON.",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.15,
                max_tokens=12_000,
            ),
            timeout=LLM_EXTRACTION_TIMEOUT_SECONDS,
        )
    except (asyncio.TimeoutError, TimeoutError):
        # The caller deterministically falls back to the local extractor.  An
        # empty plan is intentional and is distinguishable from malformed JSON.
        return {}
    except Exception:
        # A missing/unavailable provider should not make an uploaded document
        # disappear.  Preserve the same fallback contract as a timeout.
        return {}
    try:
        plan = await load_llm_json(raw, expected="object")
    except Exception:
        return {}
    return plan if isinstance(plan, dict) else {}


def merge_chunk_extractions(plans: list[dict], *, source_title: str, page_count: int = 0) -> dict:
    """确定性合并分块抽取结果并按名称去重(取更长字段值,并集 page_refs)。"""
    from services.ingest_engine import _clean_item_title  # 惰性导入避免循环依赖

    def merge_items(items: list[dict], fields: tuple[str, ...]) -> list[dict]:
        merged: dict[str, dict] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            name = _clean_item_title(str(item.get("name") or item.get("title") or ""))
            if not name:
                continue
            k = name.lower()
            if k not in merged:
                merged[k] = {**item, "name": name}
                continue
            target = merged[k]
            for field in fields:
                old = str(target.get(field) or "").strip()
                new = str(item.get(field) or "").strip()
                if new and (not old or len(new) > len(old)):
                    target[field] = new
            for field in ("related", "page_refs"):
                values = target.setdefault(field, [])
                for value in item.get(field, []) or []:
                    if value not in values:
                        values.append(value)
        return list(merged.values())

    concepts: list[dict] = []
    facts: list[dict] = []
    formulas: list[dict] = []
    principles: list[dict] = []
    summaries: list[str] = []
    tags: list[str] = []

    for plan in plans:
        if not isinstance(plan, dict):
            continue
        concepts.extend([x for x in plan.get("concepts", []) or [] if isinstance(x, dict)])
        facts.extend([x for x in plan.get("facts", []) or [] if isinstance(x, dict)])
        formulas.extend([x for x in plan.get("formulas", []) or [] if isinstance(x, dict)])
        principles.extend([x for x in plan.get("principles", []) or [] if isinstance(x, dict)])
        summary = str(plan.get("chunk_summary") or "").strip()
        if summary:
            summaries.append(summary)
        for tag in plan.get("topic_tags", []) or []:
            tag = str(tag).strip()
            if tag and tag not in tags:
                tags.append(tag)

    return {
        "summary": " ".join(summaries[:4]) or f"{source_title} 的分块知识抽取结果。",
        "tags": tags[:8],
        "concepts": merge_items(concepts, ("definition",)),
        "facts": merge_items(facts, ("statement",)),
        "formulas": merge_items(formulas, ("latex", "variables", "applications")),
        "principles": merge_items(principles, ("statement", "conditions")),
        "page_count_estimate": page_count,
        "planning_source": "llm",
    }


def _normalize_plan(plan: dict, *, source_title: str, page_count: int = 0) -> dict:
    """把单次全文抽取的 LLM 输出规整成 core_plan 形状。"""
    return {
        "summary": str(plan.get("chunk_summary") or "").strip() or f"文档：{source_title}",
        "tags": [str(t) for t in (plan.get("topic_tags") or [])][:8],
        "concepts": plan.get("concepts", []) or [],
        "facts": plan.get("facts", []) or [],
        "formulas": plan.get("formulas", []) or [],
        "principles": plan.get("principles", []) or [],
        "page_count_estimate": plan.get("page_count_estimate", page_count),
        "planning_source": "llm",
    }


async def _emit(emit, event: str, **kwargs) -> None:
    if emit is None:
        return
    try:
        await emit(event, **kwargs)
    except Exception:
        pass


async def extract_knowledge_units(
    content: str,
    *,
    source_title: str,
    page_count: int = 0,
    project_id: str = "default",
    emit=None,
    source_relative_path: str = "",
) -> dict:
    """导入管线第一阶段入口:文档内容 → core_plan。

    长文档按页分块并发抽取(信号量 3)后合并;短文档全文单次抽取
    (超过 24k 字符截断)。
    """
    chunks = build_page_chunks(content, source_title=source_title, project_id=project_id)
    if not chunks:
        max_chars = 24_000
        snippet = content if len(content) <= max_chars else content[:max_chars] + "\n\n[... truncated ...]"
        page_range = "全文" if len(content) <= max_chars else f"全文（截断至 {max_chars} 字符）"
        result = await extract_chunk(snippet, source_title=source_title, page_range=page_range)
        return _normalize_plan(result, source_title=source_title, page_count=page_count)

    await _emit(emit, "info", source=source_relative_path,
                message=f"长文档分块抽取: {len(chunks)} 个页面块")

    semaphore = asyncio.Semaphore(3)

    async def bounded(chunk: dict) -> dict:
        async with semaphore:
            return await extract_chunk(
                chunk["content"],
                source_title=source_title,
                page_range=f"第 {chunk['start_page']}-{chunk['end_page']} 页",
            )

    results = await asyncio.gather(
        *(bounded(chunk) for chunk in chunks),
        return_exceptions=True,
    )
    valid = [r for r in results if isinstance(r, dict)]
    merged = merge_chunk_extractions(valid, source_title=source_title, page_count=page_count)

    await _emit(emit, "info", source=source_relative_path,
                message=(f"分块抽取完成: {len(valid)}/{len(chunks)} 块成功; "
                         f"{len(merged.get('concepts', []))} 概念, "
                         f"{len(merged.get('facts', []))} 事实, "
                         f"{len(merged.get('formulas', []))} 公式, "
                         f"{len(merged.get('principles', []))} 原理"))
    return merged
