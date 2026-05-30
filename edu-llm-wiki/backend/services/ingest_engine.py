"""Two-step Chain-of-Thought Ingest Engine.

Step 1 (Analysis): LLM reads document -> structured analysis of concepts, formulas, relationships
Step 2 (Generation): LLM takes analysis -> generates wiki pages with cross-references
"""

import json
import asyncio
from pathlib import Path
from config import settings
from services.llm_client import chat_complete
from services.file_parser import parse_file
from storage.wiki_store import (
    write_wiki_page, compute_source_hash, get_ingest_cache, set_ingest_cache,
    update_index, sources_path, ensure_dirs, read_wiki_page,
)


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
      "parent_concept": "broader concept if applicable"
    }}
  ],
  "formulas": [
    {{
      "name": "Formula/equation name",
      "latex": "LaTeX expression",
      "variables": "Explanation of each variable",
      "applications": "When and how this formula is used"
    }}
  ],
  "principles": [
    {{
      "name": "Principle/theorem name",
      "statement": "Formal statement",
      "conditions": "Conditions under which it applies",
      "derivation_summary": "Brief derivation outline",
      "applications": "Practical applications"
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
    "tags": ["量子力学", "基础概念"]
  }}
]
```
"""


async def read_context() -> str:
    """Read purpose.md and index.md for context."""
    from storage.wiki_store import wiki_path
    context_parts = []
    for fname in ["purpose.md", "index.md", "schema.md"]:
        fpath = wiki_path() / fname
        if fpath.exists():
            content = fpath.read_text(encoding="utf-8")
            context_parts.append(f"## {fname}\n\n{content[:2000]}")
    return "\n\n".join(context_parts)


async def run_ingest(source_relative_path: str, force: bool = False) -> dict:
    """Run the two-step ingest pipeline for a single source file.

    Returns: {source, status, wiki_pages_created, wiki_pages_updated, concepts_extracted, error}
    """
    ensure_dirs()
    sp = sources_path()
    source_path = sp / source_relative_path

    if not source_path.exists():
        return {"source": source_relative_path, "status": "error", "error": "File not found"}

    # Step 0: Check cache
    content_hash = compute_source_hash(str(source_path))
    if not force:
        cached = get_ingest_cache(source_relative_path)
        if cached == content_hash:
            return {"source": source_relative_path, "status": "cached",
                    "wiki_pages_created": [], "wiki_pages_updated": []}

    # Parse file
    try:
        content = await parse_file(str(source_path))
    except Exception as e:
        return {"source": source_relative_path, "status": "error", "error": f"Parse error: {e}"}

    # Truncate if too long
    max_chars = 60000
    if len(content) > max_chars:
        content = content[:max_chars] + "\n\n[Content truncated...]"

    # Step 1: Analysis
    try:
        context = await read_context()
        analysis_raw = await chat_complete(
            system_prompt="You are an expert educational content analyzer. Output ONLY valid JSON.",
            messages=[{"role": "user", "content": ANALYSIS_PROMPT.format(
                content=content, context=context[:3000]
            )}],
            temperature=0.2,
            max_tokens=4096,
        )
        # Strip markdown code fences if present
        analysis_raw = analysis_raw.strip()
        if analysis_raw.startswith("```"):
            analysis_raw = analysis_raw.split("```")[1]
            if analysis_raw.startswith("json"):
                analysis_raw = analysis_raw[4:]
        analysis = json.loads(analysis_raw)
    except Exception as e:
        return {"source": source_relative_path, "status": "error",
                "error": f"Analysis error: {e}"}

    # Step 2: Generation
    try:
        purpose = (wiki_path := Path(settings.wiki_dir), wiki_path / "purpose.md")
        schema = (wiki_path := Path(settings.wiki_dir), wiki_path / "schema.md")
        purpose_text = purpose[0].read_text(encoding="utf-8")[:3000] if purpose[0].exists() else "Not defined yet"
        schema_text = schema[0].read_text(encoding="utf-8")[:3000] if schema[0].exists() else "Not defined yet"

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
            existing = read_wiki_page(path)
            write_wiki_page(
                relative_path=path,
                title=page["title"],
                page_type=page.get("page_type", "concept"),
                content=page.get("content", ""),
                sources=page.get("sources", [source_relative_path]),
                tags=page.get("tags", []),
            )
            if existing:
                updated.append(path)
            else:
                created.append(path)

            if page.get("page_type") == "concept":
                concepts.append(page["title"])
        except Exception as write_err:
            continue

    # Always create source summary
    source_summary_path = f"sources/{source_relative_path.rsplit('.', 1)[0].replace('/', '_')}.md"
    source_summary = write_wiki_page(
        relative_path=source_summary_path,
        title=source_relative_path,
        page_type="source",
        content=analysis.get("summary", f"# {source_relative_path}\n\nContent analysis pending."),
        sources=[source_relative_path],
    )

    if source_summary:
        created.append(source_summary_path)

    # Update index
    all_new = [{"path": p["path"], "title": p["title"], "type": p.get("page_type", "concept")}
               for p in pages]
    update_index(all_new)

    # Save cache
    set_ingest_cache(source_relative_path, content_hash)

    return {
        "source": source_relative_path,
        "status": "generated",
        "wiki_pages_created": created,
        "wiki_pages_updated": updated,
        "concepts_extracted": concepts,
    }
