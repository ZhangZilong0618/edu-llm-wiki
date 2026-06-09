"""Two-step Chain-of-Thought Ingest Engine.

Step 1 (Analysis): LLM reads document -> structured analysis of concepts, formulas, relationships
Step 2 (Generation): LLM takes analysis -> generates wiki pages with cross-references

Supports concurrent processing with configurable concurrency limit.
"""

import asyncio
import json
import re

from services.file_parser import parse_file
from services.llm_client import chat_complete
from storage.wiki_store import (
    compute_source_hash,
    ensure_dirs,
    get_ingest_cache,
    read_wiki_page,
    set_ingest_cache,
    sources_path,
    update_index,
    wiki_path,
    write_wiki_page,
)


def _strip_images(content: str) -> str:
    """Remove all image references from content before sending to LLM.

    Prevents LLM errors when content contains image references
    that the model cannot process.
    """
    # Remove markdown images: ![alt](url)
    content = re.sub(r'!\[[^\]]*\]\([^)]+\)', '', content)
    # Remove HTML img tags
    content = re.sub(r'<img[^>]*/?>', '', content)
    # Remove data URIs
    content = re.sub(r'data:image/[a-zA-Z]+;base64,[A-Za-z0-9+/=]{50,}', '', content)
    # Remove bare image file references like (image.png), [image.png], image.png on its own line
    content = re.sub(r'\b[a-zA-Z0-9_-]+\.(?:png|jpe?g|gif|bmp|tiff?|webp|svg)\b', '', content, flags=re.IGNORECASE)
    # Remove any remaining /api/media/ paths
    content = re.sub(r'/api/media/[^\s\)]+', '', content)
    # Remove lines that are just image-like filenames after above stripping
    content = re.sub(r'^[ \t]*\([\s]*\)[ \t]*$', '', content, flags=re.MULTILINE)
    content = re.sub(r'^[ \t]*\[[\s]*\][ \t]*$', '', content, flags=re.MULTILINE)
    # Clean up multiple blank lines left after removal
    content = re.sub(r'\n{3,}', '\n\n', content)
    return content


def _sync_vectors(pages: list[dict], *, project_id: str = "default"):
    """Update vector index for newly created/updated pages."""
    try:
        from services.vector_store import index_single_page
        for p in pages:
            page_data = read_wiki_page(p["path"], project_id=project_id)
            if page_data:
                index_single_page({
                    "path": p["path"],
                    "title": p.get("title", ""),
                    "type": p.get("page_type", p.get("type", "")),
                    "content": page_data.get("content", ""),
                }, project_id=project_id)
    except Exception as e:
        print(f"[ingest] Vector sync skipped: {e}")


ANALYSIS_PROMPT = """You are an expert educational content analyzer. Your task is to analyze the provided document and extract structured knowledge for a subject knowledge base.

## Document Content
{content}

## Existing Wiki Context
{context}

## Instructions
Analyze the document and output a JSON object with the following structure:

```json
{{
  "summary": "A 2-3 sentence summary of what this document teaches",
  "concepts": [
    {{
      "name": "Concept name (concise, in source language)",
      "definition": "Clear definition or explanation",
      "related_concepts": ["related concept names"],
      "parent_concept": "broader concept if applicable",
      "prerequisites": ["concept names that must be understood BEFORE this one"]
    }}
  ],
  "formulas": [
    {{
      "name": "Formula/equation name",
      "latex": "LaTeX expression",
      "variables": "Explanation of each variable",
      "applications": "When and how this formula is used",
      "prerequisites": ["concept/formula names that must be understood BEFORE this one"]
    }}
  ],
  "principles": [
    {{
      "name": "Principle/theorem name",
      "statement": "Formal statement",
      "conditions": "Conditions under which it applies",
      "derivation_summary": "Brief derivation outline",
      "applications": "Practical applications",
      "prerequisites": ["concept/principle names that must be understood BEFORE this one"]
    }}
  ],
  "exercises": [
    {{
      "question": "Exercise question text",
      "solution": "Solution or answer",
      "knowledge_points": ["knowledge point names this exercise tests"]
    }}
  ],
  "relationships": [
    {{
      "from": "concept/formula/principle name",
      "to": "concept/formula/principle name",
      "type": "prerequisite|derives|applies_to|related",
      "description": "nature of the relationship"
    }}
  ],
  "knowledge_gaps": ["areas where this document raises questions but doesn't fully answer"],
  "review_items": ["items that may need human review or verification"]
}}
```

IMPORTANT for prerequisites:
- Every concept/formula/principle MUST have a prerequisites array listing the names of concepts that must be understood BEFORE this one.
- If a concept is truly foundational (no prerequisites), use an empty array []
- Prerequisites should reference other items from the concepts/formulas/principles lists BY EXACT NAME
- Think carefully about the learning order: what must a student know before understanding this item?
- NEVER leave prerequisites out — even basic concepts can reference other foundational items

CRITICAL: Output ONLY the JSON object, no other text. Ensure valid JSON.
"""

GENERATION_PROMPT = """You are an expert educational content creator. Your task is to generate structured wiki pages from an analysis of educational content.

## Document Analysis
{analysis}

## Purpose (Educational Goals)
{purpose}

## Schema (Page Structure Rules)
{schema}

## Instructions
Based on the analysis, generate wiki pages. For each page, output a JSON object with:
- path: relative path within wiki/ (e.g., "concepts/quantum_state.md")
- title: page title
- page_type: concept | formula | principle | exercise | source
- content: full markdown content with [[wikilinks]] for cross-references
- sources: list of source file references
- tags: list of relevant tags
- prerequisites: list of page paths that must be understood BEFORE this page (e.g., ["concepts/lattice_wave.md"]). EVERY page must have this field — use [] only for genuinely foundational topics with no prerequisites.

Return a JSON array of page objects. The source summary MUST always be created.
CRITICAL: Output ONLY the JSON array, no other text. Ensure valid JSON.

Example:
```json
[
  {{
    "path": "concepts/quantum_state.md",
    "title": "量子态",
    "page_type": "concept",
    "content": "# 量子态\\n\\n## 定义\\n量子态是量子力学中描述物理系统状态的基本概念...\\n\\n## 相关概念\\n- [[concepts/wave_function]] - 波函数\\n- [[principles/superposition]] - 叠加原理",
    "sources": ["lecture_5_quantum.pdf"],
    "tags": ["量子力学", "基础概念"],
    "prerequisites": ["concepts/wave_function.md"]
  }}
]
```
"""


def _repair_json(text: str) -> str:
    """Repair malformed JSON from LLM output — markdown fences, trailing text, truncation."""
    import re

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


async def read_context(project_id: str = "default") -> str:
    """Read purpose.md and index.md for context."""
    from storage.wiki_store import wiki_path
    context_parts = []
    for fname in ["purpose.md", "index.md", "schema.md"]:
        fpath = wiki_path(project_id) / fname
        if fpath.exists():
            content = _strip_images(fpath.read_text(encoding="utf-8"))
            context_parts.append(f"## {fname}\n\n{content[:2000]}")
    return "\n\n".join(context_parts)


async def run_ingest(source_relative_path: str, force: bool = False, *, project_id: str = "default") -> dict:
    """Run the two-step ingest pipeline for a single source file.

    Returns: {source, status, wiki_pages_created, wiki_pages_updated, concepts_extracted, error}
    """
    ensure_dirs(project_id=project_id)
    sp = sources_path(project_id)
    source_path = sp / source_relative_path

    if not source_path.exists():
        return {"source": source_relative_path, "status": "error", "error": "File not found"}

    # Step 0: Check cache
    content_hash = compute_source_hash(str(source_path))
    if not force:
        cached = get_ingest_cache(source_relative_path, project_id=project_id)
        if cached == content_hash:
            return {"source": source_relative_path, "status": "cached",
                    "wiki_pages_created": [], "wiki_pages_updated": []}

    # Parse file
    try:
        wp = wiki_path(project_id)
        media_dir = str(wp / "media")
        content, extracted_images = await parse_file(str(source_path), media_dir=media_dir)
    except Exception as e:
        return {"source": source_relative_path, "status": "error", "error": f"Parse error: {e}"}

    # Truncate if too long and strip embedded images
    max_chars = 60000
    content = _strip_images(content)
    if len(content) > max_chars:
        content = content[:max_chars] + "\n\n[Content truncated...]"

    # Step 1: Analysis
    try:
        context = await read_context(project_id=project_id)
        analysis_raw = await chat_complete(
            system_prompt="You are an expert educational content analyzer. Output ONLY valid JSON.",
            messages=[{"role": "user", "content": ANALYSIS_PROMPT.format(
                content=content, context=context[:3000]
            )}],
            temperature=0.2,
            max_tokens=8192,
        )
        # Strip markdown code fences if present
        analysis_raw = analysis_raw.strip()
        if analysis_raw.startswith("```"):
            analysis_raw = analysis_raw.split("```")[1]
            if analysis_raw.startswith("json"):
                analysis_raw = analysis_raw[4:]
        # Repair truncated JSON by closing open structures
        analysis_raw = _repair_json(analysis_raw)
        analysis = json.loads(analysis_raw)
    except Exception as e:
        return {"source": source_relative_path, "status": "error",
                "error": f"Analysis error: {e}"}

    # Step 2: Generation
    try:
        wp = wiki_path(project_id)
        purpose_path = wp / "purpose.md"
        schema_path = wp / "schema.md"
        purpose_text = purpose_path.read_text(encoding="utf-8")[:3000] if purpose_path.exists() else "Not defined yet"
        schema_text = schema_path.read_text(encoding="utf-8")[:3000] if schema_path.exists() else "Not defined yet"

        gen_raw = await chat_complete(
            system_prompt="You are an expert educational content creator. Output ONLY valid JSON array.",
            messages=[{"role": "user", "content": GENERATION_PROMPT.format(
                analysis=json.dumps(analysis, ensure_ascii=False, indent=2),
                purpose=purpose_text,
                schema=schema_text,
            )}],
            temperature=0.3,
            max_tokens=8192,
        )
        gen_raw = gen_raw.strip()
        if gen_raw.startswith("```"):
            gen_raw = gen_raw.split("```")[1]
            if gen_raw.startswith("json"):
                gen_raw = gen_raw[4:]
        gen_raw = _repair_json(gen_raw)
        pages = json.loads(gen_raw)
    except Exception as e:
        return {"source": source_relative_path, "status": "error",
                "error": f"Generation error: {e}"}

    # Write pages
    created = []
    updated = []
    concepts = []

    for page in pages:
        try:
            path = page["path"]
            existing = read_wiki_page(path, project_id=project_id)
            write_wiki_page(
                relative_path=path,
                title=page["title"],
                page_type=page.get("page_type", "concept"),
                content=page.get("content", ""),
                sources=page.get("sources", [source_relative_path]),
                tags=page.get("tags", []),
                prerequisites=page.get("prerequisites", []),
                project_id=project_id,
            )
            if existing:
                updated.append(path)
            else:
                created.append(path)

            if page.get("page_type") == "concept":
                concepts.append(page["title"])
        except Exception:
            continue

    # Always create source summary
    source_summary_path = f"sources/{source_relative_path.rsplit('.', 1)[0].replace('/', '_')}.md"
    source_summary = write_wiki_page(
        relative_path=source_summary_path,
        title=source_relative_path,
        page_type="source",
        content=analysis.get("summary", f"# {source_relative_path}\n\nContent analysis pending."),
        sources=[source_relative_path],
        project_id=project_id,
    )

    if source_summary:
        created.append(source_summary_path)

    # Update index
    all_new = [{"path": p["path"], "title": p["title"], "type": p.get("page_type", "concept")}
               for p in pages]
    update_index(all_new, project_id=project_id)

    # Save cache
    set_ingest_cache(source_relative_path, content_hash, project_id=project_id)

    # Sync vectors
    _sync_vectors(pages, project_id=project_id)

    return {
        "source": source_relative_path,
        "status": "generated",
        "wiki_pages_created": created,
        "wiki_pages_updated": updated,
        "concepts_extracted": concepts,
    }


async def run_ingest_streaming(source_paths: list[str], force: bool = False, *, project_id: str = "default"):
    """Streaming version of run_ingest — yields progress events as SSE dicts."""

    async def emit(event: str, **kwargs):
        return {"event": event, **kwargs}

    for source_relative_path in source_paths:
        ensure_dirs(project_id=project_id)
        sp = sources_path(project_id)
        source_path = sp / source_relative_path

        if not source_path.exists():
            yield await emit("error", source=source_relative_path, message="File not found")
            continue

        # Cache check
        content_hash = compute_source_hash(str(source_path))
        if not force:
            cached = get_ingest_cache(source_relative_path, project_id=project_id)
            if cached == content_hash:
                yield await emit("cached", source=source_relative_path, message="Already processed (cached)")
                continue

        # Parse
        yield await emit("stage", source=source_relative_path,
                        stage="parse", message=f"正在解析文件: {source_relative_path}")
        try:
            wp = wiki_path(project_id)
            media_dir = str(wp / "media")
            content, extracted_images = await parse_file(str(source_path), media_dir=media_dir)
        except Exception as e:
            yield await emit("error", source=source_relative_path, message=f"解析失败: {e}")
            continue

        max_chars = 60000
        content = _strip_images(content)
        truncated = len(content) > max_chars
        if truncated:
            content = content[:max_chars] + "\n\n[Content truncated...]"
        yield await emit("stage_done", source=source_relative_path,
                        stage="parse",
                        message=f"解析完成: {len(content):,} 字符" + (" (已截断)" if truncated else ""))

        # Step 1: Analysis
        yield await emit("stage", source=source_relative_path,
                        stage="analyze", message="Step 1/2: LLM 正在分析文档结构...")
        try:
            context = await read_context(project_id=project_id)
            analysis_raw = await chat_complete(
                system_prompt="You are an expert educational content analyzer. Output ONLY valid JSON.",
                messages=[{"role": "user", "content": ANALYSIS_PROMPT.format(
                    content=content, context=context[:3000]
                )}],
                temperature=0.2,
                max_tokens=8192,
            )
            analysis_raw = _repair_json(analysis_raw)
            analysis = json.loads(analysis_raw)
        except Exception as e:
            yield await emit("error", source=source_relative_path, message=f"分析失败: {e}")
            continue

        # Report analysis findings in detail
        concepts_found = analysis.get("concepts", [])
        formulas_found = analysis.get("formulas", [])
        principles_found = analysis.get("principles", [])
        exercises_found = analysis.get("exercises", [])

        yield await emit("stage_done", source=source_relative_path,
                        stage="analyze",
                        message=f"分析完成: {len(concepts_found)} 个概念, {len(formulas_found)} 个公式, "
                                f"{len(principles_found)} 个原理, {len(exercises_found)} 个习题",
                        details={
                            "concepts": [c.get("name", "") for c in concepts_found[:10]],
                            "formulas": [f.get("name", "") for f in formulas_found[:5]],
                            "principles": [p.get("name", "") for p in principles_found[:5]],
                            "exercises": [e.get("question", "")[:40] for e in exercises_found[:5]],
                        })

        # Step 2: Generation
        yield await emit("stage", source=source_relative_path,
                        stage="generate",
                        message=f"Step 2/2: LLM 正在生成 Wiki 页面..."
                              f"({len(concepts_found)} 概念 + {len(formulas_found)} 公式 "
                              f"+ {len(principles_found)} 原理 + {len(exercises_found)} 习题)")
        try:
            wp = wiki_path(project_id)
            purpose_path = wp / "purpose.md"
            schema_path = wp / "schema.md"
            purpose_text = purpose_path.read_text(encoding="utf-8")[:3000] if purpose_path.exists() else "Not defined yet"
            schema_text = schema_path.read_text(encoding="utf-8")[:3000] if schema_path.exists() else "Not defined yet"

            gen_raw = await chat_complete(
                system_prompt="You are an expert educational content creator. Output ONLY valid JSON array.",
                messages=[{"role": "user", "content": GENERATION_PROMPT.format(
                    analysis=json.dumps(analysis, ensure_ascii=False, indent=2),
                    purpose=purpose_text,
                    schema=schema_text,
                )}],
                temperature=0.3,
                max_tokens=8192,
            )
            gen_raw = _repair_json(gen_raw)
            pages = json.loads(gen_raw)
        except Exception as e:
            yield await emit("error", source=source_relative_path, message=f"生成失败: {e}")
            continue

        yield await emit("stage_done", source=source_relative_path,
                        stage="generate",
                        message=f"LLM 生成了 {len(pages)} 个页面")

        # Write pages one by one with per-page progress
        yield await emit("stage", source=source_relative_path,
                        stage="write",
                        message=f"正在写入 {len(pages)} 个页面...",
                        total=len(pages))

        created = []
        updated = []
        for i, page in enumerate(pages):
            try:
                path = page["path"]
                title = page.get("title", path)
                ptype = page.get("page_type", "concept")
                existing = read_wiki_page(path, project_id=project_id)
                write_wiki_page(
                    relative_path=path,
                    title=title,
                    page_type=ptype,
                    content=page.get("content", ""),
                    sources=page.get("sources", [source_relative_path]),
                    tags=page.get("tags", []),
                    prerequisites=page.get("prerequisites", []),
                    project_id=project_id,
                )
                action = "更新" if existing else "新建"
                (updated if existing else created).append(path)
                yield await emit("write_page", source=source_relative_path,
                                message=f"[{i + 1}/{len(pages)}] {action}: {title} ({ptype})",
                                current=i + 1, total=len(pages),
                                title=title, page_type=ptype, action=action)
            except Exception:
                yield await emit("write_page", source=source_relative_path,
                                message=f"[{i + 1}/{len(pages)}] 跳过: {page.get('title', page.get('path', '?'))}",
                                current=i + 1, total=len(pages),
                                skipped=True)
        yield await emit("stage_done", source=source_relative_path,
                        stage="write",
                        message=f"写入完成: {len(created)} 新建, {len(updated)} 更新",
                        created=len(created), updated=len(updated), total=len(pages))

        # Source summary
        source_summary_path = f"sources/{source_relative_path.rsplit('.', 1)[0].replace('/', '_')}.md"
        write_wiki_page(
            relative_path=source_summary_path,
            title=source_relative_path,
            page_type="source",
            content=analysis.get("summary", f"# {source_relative_path}\n\nContent analysis pending."),
            sources=[source_relative_path],
            project_id=project_id,
        )
        created.append(source_summary_path)

        # Update index
        all_new = [{"path": p["path"], "title": p["title"], "type": p.get("page_type", "concept")}
                   for p in pages]
        update_index(all_new, project_id=project_id)

        # Save cache
        set_ingest_cache(source_relative_path, content_hash, project_id=project_id)

        # Sync vectors
        _sync_vectors(pages, project_id=project_id)

        yield await emit("complete", source=source_relative_path,
                        message=f"Done: {len(created)} pages created",
                        created=created, updated=updated)


# ─── Concurrent Batch Ingest ───────────────────────────────────────

DEFAULT_CONCURRENCY = 3


async def _run_single_with_events(
    source_relative_path: str,
    force: bool,
    project_id: str,
    emit_queue: asyncio.Queue,
):
    """Run ingest for a single file and push events to the shared queue."""
    async def emit(event: str, **kwargs):
        await emit_queue.put({"event": event, **kwargs})

    ensure_dirs(project_id=project_id)
    sp = sources_path(project_id)
    source_path = sp / source_relative_path

    if not source_path.exists():
        await emit("error", source=source_relative_path, message="File not found")
        return

    # Cache check
    content_hash = compute_source_hash(str(source_path))
    if not force:
        cached = get_ingest_cache(source_relative_path, project_id=project_id)
        if cached == content_hash:
            await emit("cached", source=source_relative_path, message="Already processed (cached)")
            return

    # Parse
    await emit("stage", source=source_relative_path,
               stage="parse", message=f"正在解析文件: {source_relative_path}")
    try:
        wp = wiki_path(project_id)
        media_dir = str(wp / "media")
        content, extracted_images = await parse_file(str(source_path), media_dir=media_dir)
    except Exception as e:
        await emit("error", source=source_relative_path, message=f"解析失败: {e}")
        return

    max_chars = 60000
    content = _strip_images(content)
    truncated = len(content) > max_chars
    if truncated:
        content = content[:max_chars] + "\n\n[Content truncated...]"
    await emit("stage_done", source=source_relative_path,
               stage="parse",
               message=f"解析完成: {len(content):,} 字符" + (" (已截断)" if truncated else ""))

    # Step 1: Analysis
    await emit("stage", source=source_relative_path,
               stage="analyze", message="Step 1/2: LLM 正在分析文档结构...")
    try:
        context = await read_context(project_id=project_id)
        analysis_raw = await chat_complete(
            system_prompt="You are an expert educational content analyzer. Output ONLY valid JSON.",
            messages=[{"role": "user", "content": ANALYSIS_PROMPT.format(
                content=content, context=context[:3000]
            )}],
            temperature=0.2,
            max_tokens=8192,
        )
        analysis_raw = _repair_json(analysis_raw)
        analysis = json.loads(analysis_raw)
    except Exception as e:
        await emit("error", source=source_relative_path, message=f"分析失败: {e}")
        return

    concepts_found = analysis.get("concepts", [])
    formulas_found = analysis.get("formulas", [])
    principles_found = analysis.get("principles", [])
    exercises_found = analysis.get("exercises", [])

    await emit("stage_done", source=source_relative_path,
               stage="analyze",
               message=f"分析完成: {len(concepts_found)} 个概念, {len(formulas_found)} 个公式, "
                       f"{len(principles_found)} 个原理, {len(exercises_found)} 个习题",
               details={
                   "concepts": [c.get("name", "") for c in concepts_found[:10]],
                   "formulas": [f.get("name", "") for f in formulas_found[:5]],
                   "principles": [p.get("name", "") for p in principles_found[:5]],
                   "exercises": [e.get("question", "")[:40] for e in exercises_found[:5]],
               })

    # Step 2: Generation
    await emit("stage", source=source_relative_path,
               stage="generate",
               message=f"Step 2/2: LLM 正在生成 Wiki 页面..."
                       f"({len(concepts_found)} 概念 + {len(formulas_found)} 公式 "
                       f"+ {len(principles_found)} 原理 + {len(exercises_found)} 习题)")
    try:
        wp = wiki_path(project_id)
        purpose_path = wp / "purpose.md"
        schema_path = wp / "schema.md"
        purpose_text = purpose_path.read_text(encoding="utf-8")[:3000] if purpose_path.exists() else "Not defined yet"
        schema_text = schema_path.read_text(encoding="utf-8")[:3000] if schema_path.exists() else "Not defined yet"

        gen_raw = await chat_complete(
            system_prompt="You are an expert educational content creator. Output ONLY valid JSON array.",
            messages=[{"role": "user", "content": GENERATION_PROMPT.format(
                analysis=json.dumps(analysis, ensure_ascii=False, indent=2),
                purpose=purpose_text,
                schema=schema_text,
            )}],
            temperature=0.3,
            max_tokens=8192,
        )
        gen_raw = _repair_json(gen_raw)
        pages = json.loads(gen_raw)
    except Exception as e:
        await emit("error", source=source_relative_path, message=f"生成失败: {e}")
        return

    await emit("stage_done", source=source_relative_path,
               stage="generate",
               message=f"LLM 生成了 {len(pages)} 个页面")

    # Write pages
    await emit("stage", source=source_relative_path,
               stage="write",
               message=f"正在写入 {len(pages)} 个页面...",
               total=len(pages))

    created = []
    updated = []
    for i, page in enumerate(pages):
        try:
            path = page["path"]
            title = page.get("title", path)
            ptype = page.get("page_type", "concept")
            existing = read_wiki_page(path, project_id=project_id)
            write_wiki_page(
                relative_path=path,
                title=title,
                page_type=ptype,
                content=page.get("content", ""),
                sources=page.get("sources", [source_relative_path]),
                tags=page.get("tags", []),
                prerequisites=page.get("prerequisites", []),
                project_id=project_id,
            )
            action = "更新" if existing else "新建"
            (updated if existing else created).append(path)
            await emit("write_page", source=source_relative_path,
                       message=f"[{i + 1}/{len(pages)}] {action}: {title} ({ptype})",
                       current=i + 1, total=len(pages),
                       title=title, page_type=ptype, action=action)
        except Exception:
            await emit("write_page", source=source_relative_path,
                       message=f"[{i + 1}/{len(pages)}] 跳过: {page.get('title', page.get('path', '?'))}",
                       current=i + 1, total=len(pages),
                       skipped=True)
    await emit("stage_done", source=source_relative_path,
               stage="write",
               message=f"写入完成: {len(created)} 新建, {len(updated)} 更新",
               created=len(created), updated=len(updated), total=len(pages))

    # Source summary
    source_summary_path = f"sources/{source_relative_path.rsplit('.', 1)[0].replace('/', '_')}.md"
    write_wiki_page(
        relative_path=source_summary_path,
        title=source_relative_path,
        page_type="source",
        content=analysis.get("summary", f"# {source_relative_path}\n\nContent analysis pending."),
        sources=[source_relative_path],
        project_id=project_id,
    )
    created.append(source_summary_path)

    # Update index
    all_new = [{"path": p["path"], "title": p["title"], "type": p.get("page_type", "concept")}
               for p in pages]
    update_index(all_new, project_id=project_id)

    # Save cache
    set_ingest_cache(source_relative_path, content_hash, project_id=project_id)

    # Sync vectors
    _sync_vectors(pages, project_id=project_id)

    await emit("complete", source=source_relative_path,
               message=f"Done: {len(created)} pages created",
               created=created, updated=updated)


async def run_ingest_batch_streaming(
    source_paths: list[str],
    force: bool = False,
    concurrency: int = DEFAULT_CONCURRENCY,
    *,
    project_id: str = "default",
):
    """Concurrent batch ingest — processes multiple files in parallel with a semaphore.

    Yields SSE events from all files interleaved. Each event includes a 'source' field
    to identify which file it belongs to.
    """
    queue: asyncio.Queue = asyncio.Queue()
    semaphore = asyncio.Semaphore(concurrency)

    async def bounded_ingest(path: str):
        async with semaphore:
            await _run_single_with_events(path, force, project_id, queue)

    async def producer():
        tasks = [asyncio.create_task(bounded_ingest(p)) for p in source_paths]
        await asyncio.gather(*tasks, return_exceptions=True)
        await queue.put(None)  # sentinel: all done

    # Start producer in background
    asyncio.create_task(producer())

    # Yield events as they arrive
    while True:
        event = await queue.get()
        if event is None:
            break
        yield event
