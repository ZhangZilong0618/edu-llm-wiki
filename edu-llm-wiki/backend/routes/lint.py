"""API routes for knowledge base health check (lint)."""

from fastapi import APIRouter, Query

from services.llm_client import chat_complete
from storage.wiki_store import list_wiki_pages, wiki_path

router = APIRouter(prefix="/api/lint", tags=["lint"])


LINT_PROMPT = """You are an educational knowledge base auditor. Your task is to check the health of a structured wiki containing course materials.

## All Wiki Pages
{pages}

## Purpose
{purpose}

## Instructions
Review the wiki pages and identify:

1. **Contradictions**: Pages that make conflicting claims
2. **Stale content**: Information that may be outdated
3. **Orphan pages**: Important concepts with few or no inbound links
4. **Missing cross-references**: Concepts mentioned but lacking their own page
5. **Knowledge gaps**: Important topics that should have pages but don't
6. **Recommended actions**: Specific suggestions to improve the knowledge base

Output a JSON object:
```json
{{
  "health_score": 0-100,
  "contradictions": [{{"pages": ["path1", "path2"], "description": "..."}}],
  "orphans": [{{"path": "...", "issue": "..."}}],
  "missing_pages": ["topic1", "topic2"],
  "knowledge_gaps": ["gap description"],
  "suggestions": ["actionable suggestion"],
  "summary": "Brief health summary"
}}
```

CRITICAL: Output ONLY the JSON object, no other text.
"""


@router.post("/run")
async def run_lint(project_id: str = Query("default")):
    """Run a health check on the knowledge base."""
    pages = list_wiki_pages(project_id=project_id)
    pages_text = "\n".join([
        f"- [{p['type']}] {p['title']} ({p['path']}) - {p.get('summary', '')[:100]}"
        for p in pages
    ])

    purpose = (wiki_path(project_id) / "purpose.md").read_text(encoding="utf-8")[:2000] if (wiki_path(project_id) / "purpose.md").exists() else "Not defined"

    import json
    result = await chat_complete(
        system_prompt="You are a knowledge base auditor. Output ONLY valid JSON.",
        messages=[{"role": "user", "content": LINT_PROMPT.format(
            pages=pages_text[:15000], purpose=purpose
        )}],
        temperature=0.2,
        max_tokens=4096,
    )

    # Parse JSON from response
    result = result.strip()
    if result.startswith("```"):
        result = result.split("```")[1]
        if result.startswith("json"):
            result = result[4:]

    return json.loads(result)
