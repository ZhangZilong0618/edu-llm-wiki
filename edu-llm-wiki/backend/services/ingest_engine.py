"""Two-step Chain-of-Thought Ingest Engine.

Step 1 (Analysis): LLM reads document -> structured analysis of concepts, formulas, relationships
Step 2 (Generation): LLM takes analysis -> generates wiki pages with cross-references

Supports concurrent processing with configurable concurrency limit.
"""

import asyncio
import json
import re
from pathlib import Path

from services.file_parser import parse_file
from services.llm_client import chat_complete
from storage.wiki_store import (
    compute_source_hash,
    ensure_dirs,
    get_ingest_cache,
    read_wiki_page,
    record_source_pages,
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


def _read_preparsed_source(source_path: Path) -> str | None:
    """Use PaddleOCR parsed markdown when available; it preserves tables/formulas better for slide PDFs."""
    parsed_doc = source_path.parent / f"{source_path.name}.parsed" / "document.md"
    if not parsed_doc.exists():
        return None
    content = parsed_doc.read_text(encoding="utf-8")
    content = re.sub(r'<img[^>]*>', '', content)
    content = re.sub(r'<div[^>]*>\s*</div>', '', content)
    return content.strip() or None


async def _parse_source_content(source_path: Path, *, media_dir: str | None = None) -> tuple[str, list[dict], str]:
    preparsed = _read_preparsed_source(source_path)
    if preparsed:
        return preparsed, [], "PaddleOCR parsed markdown"
    content, images = await parse_file(str(source_path), media_dir=media_dir)
    return content, images, "file parser"


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
      "name": "Semantic formula name, not the equation itself",
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
      "type": "short_answer|multiple_choice|fill_blank",
      "question": "Exercise question text",
      "choices": ["A. option text", "B. option text"],
      "solution": "Solution or answer",
      "knowledge_points": ["knowledge point names this exercise tests"]
    }}
  ],
  "synthesis": [
    {{
      "title": "Synthesis page title",
      "focus": "What this synthesis helps the learner understand",
      "key_points": ["integrated insight, comparison, or connection"],
      "connections": ["concept/formula/principle names connected here"],
      "open_questions": ["useful follow-up questions or limitations"]
    }}
  ],
  "q_and_a": [
    {{
      "question": "A high-value learner question",
      "answer": "Clear answer grounded in the document",
      "why_it_matters": "Why this question is useful",
      "related_items": ["concept/formula/principle names"]
    }}
  ],
  "system_notes": [
    {{
      "title": "Learning/navigation note title",
      "purpose": "How this note improves the wiki or learning workflow",
      "learning_order": ["ordered concept/formula/principle names"],
      "study_strategy": ["specific learning or review action"],
      "quality_warnings": ["ambiguities, OCR issues, missing context, or things to verify"]
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

IMPORTANT for type classification:
- Put equations, coefficients, variables with equations, and named mathematical expressions in formulas, not concepts.
- Formula names MUST be semantic names, not raw equations or LaTeX. Prefer the physical quantity, law, or relationship name itself, such as "电导率", "布拉格定律", "密度", "热容关系", "Kohn-Sham 方程". Do not add "公式" just to make a title. Never use titles like "J=\\sigma E", "\\rho=m/V", "a=b\\ne c", or "\\Delta V=\\alpha\\Delta T".
- When describing formulas or equations in the output, write all math using proper LaTeX syntax: inline math must be wrapped in $...$ (e.g., $\\sigma$, $\\varepsilon$), and display equations must be wrapped in $$...$$ (e.g., $$E = \\sigma \\varepsilon$$). Do NOT leave bare LaTeX commands like \\sigma or \\varepsilon without delimiters.
- Put laws, theorems, mechanisms, effects, and named rules in principles when they describe a general relationship or causal rule.
- Put worked examples, review questions, homework questions, and calculation prompts in exercises, even if no full solution is present.
- When creating exercises, keep question types diverse when the source material allows it:
  - multiple_choice: include 3-5 choices formatted as "A. ...", "B. ..."; solution should identify the correct option and explain why.
  - fill_blank: use clear blanks such as "____" or "（ ）"; solution should list each blank answer.
  - short_answer: use for derivations, explanations, and calculations.
  Add a "type" field for every exercise. Prefer a mix instead of making every exercise short_answer.
- Never create a multiple_choice exercise without visible options in the question. If the answer begins with "A.", "B.", "C.", or "D.", the question MUST include the matching A./B./C./D. option lines. If you cannot provide options, use fill_blank or short_answer instead.
- Create exercises that are useful for practice, not generic recall only:
  - Include at least one conceptual understanding question when concepts exist.
  - Include at least one formula/application/calculation question when formulas exist.
  - Include at least one comparison/diagnosis question when the document contrasts mechanisms or categories.
  - Avoid questions whose answer is just the page title.
- Create synthesis items for cross-topic understanding, comparisons, contradictions, learning summaries, and "how the pieces fit together".
- Create q_and_a items for questions a student is likely to ask after reading this document. Answers must be grounded in the document and should clarify misconceptions.
- Create system_notes for learning order, review strategy, source quality warnings, and wiki organization. These are not content lessons; they guide how to study and maintain this imported document.
- Concepts should be reserved for definitions and entities, not every named technical term.
- If a document contains tables or paragraphs defining quantities such as thermal conductivity, absorption coefficient, Seebeck coefficient, heat capacity, or ZT, extract any accompanying equation as a formula page and the physical rule as a principle page when applicable.

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
- page_type: concept | formula | principle | exercise | source | synthesis | query | system
- content: full markdown content with [[wikilinks]] for cross-references
- sources: list of source file references
- tags: list of relevant tags
- prerequisites: list of page paths that must be understood BEFORE this page (e.g., ["concepts/lattice_wave.md"]). EVERY page must have this field — use [] only for genuinely foundational topics with no prerequisites.

Type coverage rules:
- Create concept pages for items in analysis.concepts.
- Create formula pages for every meaningful item in analysis.formulas; do NOT merge formulas into concept pages.
- Formula page titles MUST be human-readable semantic titles, not equations. Prefer the quantity/law/relationship name and avoid adding "公式" unless it is part of a recognized name. If the analysis name is an equation, infer a title from variables, applications, surrounding topic, or the known law. Keep the equation only inside the "## 公式" section.
- Create principle pages for every meaningful item in analysis.principles; do NOT merge principles into concept pages.
- Create exercise pages for every item in analysis.exercises. Exercise content MUST include a clear "## 题型" section, a clear "## 题目" section, and a separate "## 解答" or "## Answer" section. For multiple_choice, also include a separate "## 选项" section with A./B./C./D. lines. For fill_blank, keep blanks in the 题目 section.
- Multiple-choice pages are invalid without options. If a solution starts with an option letter such as "B.", the page must contain a "## 选项" section with A./B./C./D. options. Do not place options only in 解答.
- If analysis.principles is empty but formulas or mechanism concepts exist, create 1-2 principle pages that explain applicable relationships, assumptions, and boundaries.
- If analysis.exercises is empty but concepts/formulas/principles exist, create 2-4 useful exercise pages. Mix multiple_choice, fill_blank, and short_answer when possible. Do not leave Exercises empty for educational documents.
- Create synthesis pages for every item in analysis.synthesis. Synthesis pages MUST be useful study pages, not summaries only. Use sections: "## 核心综合", "## 关联知识", "## 易混点/对比", "## 进一步问题". Link related pages with [[...]] where possible.
- Create query pages for every item in analysis.q_and_a. Query pages MUST use sections: "## 问题", "## 回答", "## 为什么重要", "## 相关知识". They should be concise, searchable, and suitable for later chat retrieval.
- Create system pages for every item in analysis.system_notes. System pages MUST use sections: "## 用途", "## 推荐学习顺序", "## 复习策略", "## 质量提醒". They should guide the learner or wiki maintainer, not duplicate lesson content.
- CRITICAL: All mathematical content must be formatted with proper LaTeX delimiters: inline math as $...$ (e.g., $\\sigma$, $\\varepsilon$, $E = \\sigma \\varepsilon$) and display equations as $$...$$. Never write bare LaTeX commands like \\sigma or \\varepsilon without $...$ delimiters.
- Use source only for document summaries, never for ordinary concepts/formulas/principles/exercises.
- If synthesis, q_and_a, or system_notes are empty but the document has meaningful educational content, create one concise page of each type from the available analysis.
- Do not create empty or placeholder pages. Every generated page must contain concrete information from the document analysis.

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


async def _load_llm_json(raw: str, *, expected: str) -> object:
    """Parse LLM JSON output, asking the LLM to repair malformed JSON once if needed."""
    repaired = _repair_json(raw)
    try:
        return json.loads(repaired)
    except json.JSONDecodeError as first_error:
        fixed = await chat_complete(
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
        )
        try:
            return json.loads(_repair_json(fixed))
        except json.JSONDecodeError as second_error:
            raise ValueError(f"LLM returned malformed JSON and auto-repair failed: {second_error}") from second_error


def _slugify_title(title: str) -> str:
    title = (title or "untitled").strip()
    title = re.sub(r"^#+\s*", "", title)
    title = re.sub(r'[\\/:\*\?"<>\|]+', "_", title)
    title = re.sub(r"\s+", "_", title)
    return title[:80].strip("._ ") or "untitled"


_GENERIC_FORMULA_TITLES = {
    "公式", "电学", "热学", "力学", "磁学", "光学", "上课形式", "基本原理",
    "① 基本原理", "formula", "page",
}


def _clean_item_title(title: str) -> str:
    title = re.sub(r"^#+\s*", "", (title or "").strip())
    title = title.strip(" ：:，,。")
    return title


def _is_page_heading(title: str) -> bool:
    return bool(re.match(r"^#+?\s*Page\s+\d+\s*$", title.strip(), re.IGNORECASE))


def _is_generic_formula_title(title: str) -> bool:
    clean = _clean_item_title(title)
    return (
        not clean
        or clean in _GENERIC_FORMULA_TITLES
        or _is_page_heading(clean)
        or _looks_like_formula_title(clean)
        or len(clean) > 50
    )


def _normalize_latex(latex: str) -> str:
    latex = (latex or "").strip()
    latex = re.sub(r"^\$+\s*(?:\\n|\n)?", "", latex)
    latex = re.sub(r"(?:\\n|\n)?\s*\$+$", "", latex)
    latex = latex.replace("$$", "").strip()
    return latex


def _looks_like_formula_title(title: str) -> bool:
    clean = _clean_item_title(title)
    if not clean:
        return False
    if re.search(r"\\[a-zA-Z]+|[=≈≠≤≥<>]|[_^{}]", clean):
        return True
    symbol_count = len(re.findall(r"[+\-*/=≈≠≤≥<>α-ωΑ-ΩσρλθχβγδεμτκΩ℃°]", clean))
    letter_count = len(re.findall(r"[A-Za-zα-ωΑ-Ω]", clean))
    has_math_spacing = bool(re.search(r"\s[+\-*/=≈≠≤≥<>]\s", clean))
    return has_math_spacing or (symbol_count >= 2 and letter_count >= 1 and len(clean) <= 80)


def _formula_title_from_latex(latex: str, *, variables: str = "", applications: str = "", context: str = "") -> str:
    cleaned = _normalize_latex(latex)
    if not cleaned:
        return "未命名关系"

    compact = re.sub(r"\s+", "", cleaned)
    plain = compact.replace("\\", "")
    hint = f"{variables} {applications} {context}".lower()

    known_patterns = [
        (r"2d(?:\\sin|sin).*n(?:\\lambda|lambda|λ)", "布拉格定律"),
        (r"J=.*(?:\\sigma|sigma|σ).*E", "电流密度与电场关系"),
        (r"(?:\\rho|rho|ρ)=?(?:m/V|\\frac\{m\}\{V\}|frac\{m\}\{V\})|m/V|frac\{m\}\{V\}", "密度"),
        (r"(?:\\DeltaV|DeltaV|ΔV).*?(?:\\alpha|alpha|α).*?(?:\\DeltaT|DeltaT|ΔT)", "塞贝克效应"),
        (r"Q=.*C.*(?:\\DeltaT|DeltaT|ΔT)", "热容关系"),
        (r"M=.*(?:\\chi|chi|χ).*H", "磁化率关系"),
        (r"(?:\\ln|ln).*I/I_?0.*(?:\\alpha|alpha|α).*x", "吸收定律"),
        (r"H_?\\?{?K?S|Kohn-?Sham", "Kohn-Sham 方程"),
        (r"a=b=c", "立方晶系轴长关系"),
        (r"a=b(?:\\+ne|\\ne|ne|≠|!=)c", "四方晶系轴长关系"),
        (r"(?:\\alpha|alpha|α)=(?:\\beta|beta|β)=(?:\\gamma|gamma|γ)=90", "晶轴夹角关系"),
    ]
    for pattern, title in known_patterns:
        if re.search(pattern, compact, re.IGNORECASE) or re.search(pattern, plain, re.IGNORECASE):
            return title

    hint_titles = [
        (("conductivity", "电导率", "sigma", "σ"), "电导率"),
        (("resistivity", "电阻率", "rho", "ρ"), "电阻率"),
        (("density", "密度"), "密度"),
        (("heat capacity", "热容"), "热容关系"),
        (("bragg", "布拉格"), "布拉格定律"),
        (("seebeck", "塞贝克"), "塞贝克效应"),
        (("absorption", "吸收"), "吸收定律"),
        (("magnetization", "磁化", "susceptibility", "磁化率"), "磁化率关系"),
        (("stress", "应力", "strain", "应变"), "应力-应变关系"),
        (("crystal", "晶系", "晶胞", "晶格"), "晶系参数关系"),
    ]
    for keywords, title in hint_titles:
        if any(keyword in hint for keyword in keywords):
            return title

    left = re.split(r"=|≈|≠|≤|≥|<|>", cleaned, maxsplit=1)[0]
    left = re.sub(r"\\(?:mathrm|mathbf|text)\{([^}]+)\}", r"\1", left)
    left = re.sub(r"\\[a-zA-Z]+", "", left)
    left = re.sub(r"[_^{}\\\s]+", "", left).strip()
    symbol_titles = {
        "J": "电流密度",
        "Q": "热量关系",
        "M": "磁化强度",
        "V": "电势关系",
        "E": "能量关系",
        "H": "哈密顿量",
        "rho": "密度",
        "sigma": "电导率",
    }
    return symbol_titles.get(left, "物理量关系")


def _page_path_for(page_type: str, title: str) -> str:
    folder_by_type = {
        "concept": "concepts",
        "formula": "formulas",
        "principle": "principles",
        "exercise": "exercises",
        "source": "sources",
        "synthesis": "synthesis",
        "query": "queries",
        "system": "systems",
    }
    folder = folder_by_type.get(page_type, f"{page_type}s")
    return f"{folder}/{_slugify_title(title)}.md"


def _as_list(value) -> list:
    return value if isinstance(value, list) else []


def _bullet_list(items: list, fallback: str = "待补充") -> str:
    clean = [str(item).strip() for item in items if str(item).strip()]
    return "\n".join(f"- {item}" for item in clean) if clean else fallback


def _names_from_items(items: list[dict], key: str = "name", limit: int = 8) -> list[str]:
    names: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get(key) or item.get("title") or "").strip()
        if name and name not in names:
            names.append(name)
        if len(names) >= limit:
            break
    return names


def _formula_names_from_items(items: list[dict], limit: int = 8) -> list[str]:
    names: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        raw_title = str(item.get("name") or item.get("title") or "").strip()
        latex = _normalize_latex(str(item.get("latex") or item.get("formula") or ""))
        variables = str(item.get("variables") or "").strip()
        applications = str(item.get("applications") or "").strip()
        name = _clean_item_title(raw_title)
        if _is_generic_formula_title(name):
            name = _formula_title_from_latex(latex, variables=variables, applications=applications, context=raw_title)
        if name and name not in names:
            names.append(name)
        if len(names) >= limit:
            break
    return names


def _page_type_exists(pages: list[dict], page_type: str) -> bool:
    return any((p.get("page_type") or p.get("type")) == page_type for p in pages)


def _normalize_generated_pages(pages: list[dict], source_relative_path: str) -> list[dict]:
    normalized: list[dict] = []
    for page in pages:
        ptype = page.get("page_type") or page.get("type") or "concept"
        title = _clean_item_title(str(page.get("title") or page.get("name") or ""))
        if not title:
            continue
        page["page_type"] = ptype
        page["title"] = title
        page.setdefault("path", _page_path_for(ptype, title))
        if ptype == "formula":
            content = str(page.get("content") or "")
            content = re.sub(r"\$\$\s*(?:\\n|\n)\s*\$\$", "$$", content)
            content = content.replace("$$\\n", "$$\n").replace("\\n$$", "\n$$")
            page["content"] = content
        page.setdefault("sources", [source_relative_path])
        normalized.append(page)
    return normalized


def _ensure_pages_from_analysis(analysis: dict, pages: object, source_relative_path: str) -> list[dict]:
    """Guarantee extracted educational structures become their own wiki pages."""
    if not isinstance(pages, list):
        pages = []

    normalized_pages = _normalize_generated_pages([p for p in pages if isinstance(p, dict)], source_relative_path)
    existing = {
        (
            (p.get("page_type") or "concept"),
            (p.get("title") or "").strip().lower(),
        )
        for p in normalized_pages
    }

    def add_page(page_type: str, title: str, content: str, tags: list[str], prerequisites: list[str] | None = None):
        key = (page_type, title.strip().lower())
        if not title or key in existing:
            return
        existing.add(key)
        normalized_pages.append({
            "path": _page_path_for(page_type, title),
            "title": title,
            "page_type": page_type,
            "content": content,
            "sources": [source_relative_path],
            "tags": tags,
            "prerequisites": prerequisites or [],
        })

    for item in analysis.get("formulas", []) or []:
        if not isinstance(item, dict):
            continue
        raw_title = str(item.get("name") or item.get("title") or "").strip()
        latex = _normalize_latex(str(item.get("latex") or item.get("formula") or ""))
        variables = str(item.get("variables") or "").strip()
        applications = str(item.get("applications") or "").strip()
        title = _clean_item_title(raw_title)
        if _is_generic_formula_title(title):
            title = _formula_title_from_latex(
                latex,
                variables=variables,
                applications=applications,
                context=raw_title,
            )
        if not latex or _is_generic_formula_title(title):
            continue
        prereqs = item.get("prerequisites") if isinstance(item.get("prerequisites"), list) else []
        content = (
            f"# {title}\n\n"
            f"## 公式\n\n$$\n{latex}\n$$\n\n"
            f"## 变量说明\n\n{variables or '待补充'}\n\n"
            f"## 适用场景\n\n{applications or '待补充'}\n"
        )
        add_page("formula", title, content, ["formula"], prereqs)

    for item in analysis.get("principles", []) or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("name") or item.get("title") or "").strip()
        statement = str(item.get("statement") or "").strip()
        conditions = str(item.get("conditions") or "").strip()
        derivation = str(item.get("derivation_summary") or "").strip()
        applications = str(item.get("applications") or "").strip()
        prereqs = item.get("prerequisites") if isinstance(item.get("prerequisites"), list) else []
        content = (
            f"# {title}\n\n"
            f"## 陈述\n\n{statement or '待补充'}\n\n"
            f"## 适用条件\n\n{conditions or '待补充'}\n\n"
            f"## 推导/说明\n\n{derivation or '待补充'}\n\n"
            f"## 应用\n\n{applications or '待补充'}\n"
        )
        add_page("principle", title, content, ["principle"], prereqs)

    for idx, item in enumerate(analysis.get("exercises", []) or [], start=1):
        if not isinstance(item, dict):
            continue
        exercise_type = str(item.get("type") or item.get("question_type") or "short_answer").strip()
        question = str(item.get("question") or item.get("title") or "").strip()
        title_source = question.splitlines()[0].strip() if question else ""
        choices = item.get("choices") if isinstance(item.get("choices"), list) else []
        has_choice_options = bool(re.search(r"^\s*(?:[-*]\s*)?[A-Da-d][\.\)、:：]\s+", question, re.MULTILINE))
        clean_choices = [str(choice).strip() for choice in choices if str(choice).strip()]
        if clean_choices and not has_choice_options:
            has_choice_options = True
        title = title_source[:40] or f"练习 {idx}"
        solution = str(item.get("solution") or item.get("answer") or "").strip()
        solution_starts_with_choice = bool(re.match(r"^\s*(?:答案[:：]?\s*)?[A-Ha-h][\.\)、:：\s]", solution))
        normalized_exercise_type = exercise_type.lower().replace("-", "_").replace(" ", "_")
        if solution_starts_with_choice and has_choice_options:
            exercise_type = "multiple_choice"
        elif "multiple_choice" in normalized_exercise_type and not has_choice_options:
            exercise_type = "short_answer"
            if solution_starts_with_choice:
                solution = re.sub(r"^\s*(?:答案[:：]?\s*)?[A-Ha-h][\.\)、:：\s]*", "", solution).strip() or solution
        elif "fill" in normalized_exercise_type and solution_starts_with_choice:
            solution = re.sub(r"^\s*(?:答案[:：]?\s*)?[A-Ha-h][\.\)、:：\s]*", "", solution).strip() or solution
        knowledge_points = item.get("knowledge_points") if isinstance(item.get("knowledge_points"), list) else []
        options_section = ""
        if exercise_type == "multiple_choice" and clean_choices:
            options_section = "## 选项\n\n" + "\n".join(clean_choices) + "\n\n"
        elif exercise_type == "multiple_choice" and has_choice_options:
            option_lines = [
                line.strip()
                for line in question.splitlines()
                if re.match(r"^\s*(?:[-*]\s*)?[A-Da-d][\.\)、:：]\s+", line)
            ]
            prompt_lines = [
                line
                for line in question.splitlines()
                if not re.match(r"^\s*(?:[-*]\s*)?[A-Da-d][\.\)、:：]\s+", line)
            ]
            if option_lines:
                question = "\n".join(prompt_lines).strip() or question
                options_section = "## 选项\n\n" + "\n".join(option_lines) + "\n\n"
        content = (
            f"# {title}\n\n"
            f"## 题型\n\n{exercise_type or 'short_answer'}\n\n"
            f"## 题目\n\n{question or '待补充'}\n\n"
            f"{options_section}"
            f"## 解答\n\n{solution or '待补充'}\n\n"
            f"## 考察知识点\n\n"
            + "\n".join(f"- {kp}" for kp in knowledge_points)
            + ("\n" if knowledge_points else "待补充\n")
        )
        add_page("exercise", title, content, ["exercise"], [])

    concepts = _as_list(analysis.get("concepts"))
    formulas = _as_list(analysis.get("formulas"))
    principles = _as_list(analysis.get("principles"))
    exercises = _as_list(analysis.get("exercises"))
    concept_names = _names_from_items(concepts)
    formula_names = _formula_names_from_items(formulas)
    principle_names = _names_from_items(principles)
    exercise_names = _names_from_items(exercises, key="question", limit=5)
    all_knowledge_names = concept_names + formula_names + principle_names

    if (concepts or formulas) and not _page_type_exists(normalized_pages, "principle"):
        if formulas:
            item = next((f for f in formulas if isinstance(f, dict)), {})
            raw_title = str(item.get("name") or item.get("title") or "").strip()
            latex = _normalize_latex(str(item.get("latex") or item.get("formula") or ""))
            variables = str(item.get("variables") or "").strip()
            applications = str(item.get("applications") or "").strip()
            formula_title = _clean_item_title(raw_title)
            if _is_generic_formula_title(formula_title):
                formula_title = _formula_title_from_latex(latex, variables=variables, applications=applications, context=raw_title)
            title = f"{formula_title}的适用关系"
            content = (
                f"# {title}\n\n"
                f"## 陈述\n\n{formula_title}不是孤立的符号表达，而是描述相关物理量之间如何相互约束和变化的关系。\n\n"
                f"## 适用条件\n\n{applications or '需要结合来源文档中的上下文、变量含义和近似条件使用。'}\n\n"
                f"## 推导/说明\n\n{variables or '先明确每个变量的物理意义，再判断哪些量是原因、哪些量是结果。'}\n\n"
                f"## 应用\n\n用于解释、比较或计算与 {formula_title} 相关的问题，并帮助判断题目中给出的条件是否足够。\n"
            )
            add_page("principle", title, content, ["principle", "generated-fallback"], [])
        elif len(concept_names) >= 2:
            title = f"{concept_names[0]}与{concept_names[1]}的关系"
            content = (
                f"# {title}\n\n"
                f"## 陈述\n\n理解 {concept_names[0]} 时，需要同时辨析它和 {concept_names[1]} 的联系与区别。\n\n"
                f"## 适用条件\n\n该关系用于整理本来源文档中的核心概念网络。\n\n"
                f"## 推导/说明\n\n先分别给出两个概念的定义，再比较它们作用对象、影响因素和使用场景。\n\n"
                f"## 应用\n\n用于复习、问答和后续练习中的概念辨析。\n"
            )
            add_page("principle", title, content, ["principle", "generated-fallback"], [])

    if (concepts or formulas or principles) and not _page_type_exists(normalized_pages, "exercise"):
        primary_concept = concept_names[0] if concept_names else (formula_names[0] if formula_names else "本节核心知识")
        secondary_concept = concept_names[1] if len(concept_names) > 1 else (principle_names[0] if principle_names else primary_concept)

        mc_title = f"判断{primary_concept}的关键影响因素"
        mc_question = f"下列哪一项最有助于理解 {primary_concept}？"
        mc_options = "\n".join([
            "A. 只记住名称，不看适用条件",
            "B. 明确它涉及的物理量、适用场景和限制",
            "C. 只背诵来源文件页码",
            "D. 忽略它与其他概念的关系",
        ])
        mc_solution = f"答案：B。理解 {primary_concept} 需要把定义、变量含义、适用条件和相关知识联系起来。"
        add_page(
            "exercise",
            mc_title,
            (
                f"# {mc_title}\n\n"
                f"## 题型\n\nmultiple_choice\n\n"
                f"## 题目\n\n{mc_question}\n\n"
                f"## 选项\n\n{mc_options}\n\n"
                f"## 解答\n\n{mc_solution}\n\n"
                f"## 考察知识点\n\n- {primary_concept}\n"
            ),
            ["exercise", "generated-fallback"],
            [],
        )

        if formula_names:
            fill_title = f"补全{formula_names[0]}的变量含义"
            add_page(
                "exercise",
                fill_title,
                (
                    f"# {fill_title}\n\n"
                    f"## 题型\n\nfill_blank\n\n"
                    f"## 题目\n\n"
                    f"学习 {formula_names[0]} 时，不能只看表达式，还要说明每个符号代表的 ____、单位和适用条件。\n\n"
                    f"## 解答\n\n空格可填：物理量。完整理解公式需要同时掌握变量含义、单位、适用条件和使用目的。\n\n"
                    f"## 考察知识点\n\n- {formula_names[0]}\n"
                ),
                ["exercise", "generated-fallback"],
                [],
            )

        short_title = f"比较{primary_concept}与{secondary_concept}"
        add_page(
            "exercise",
            short_title,
            (
                f"# {short_title}\n\n"
                f"## 题型\n\nshort_answer\n\n"
                f"## 题目\n\n请用自己的话比较 {primary_concept} 和 {secondary_concept}：它们分别回答什么问题？在哪些场景下容易混淆？\n\n"
                f"## 解答\n\n应分别说明二者的定义或作用对象，再指出联系、区别和适用边界。答案需要结合来源文档中的例子或公式，而不是只罗列名称。\n\n"
                f"## 考察知识点\n\n- {primary_concept}\n- {secondary_concept}\n"
            ),
            ["exercise", "generated-fallback"],
            [],
        )

    for idx, item in enumerate(_as_list(analysis.get("synthesis")), start=1):
        if not isinstance(item, dict):
            continue
        title = _clean_item_title(str(item.get("title") or item.get("focus") or f"综合分析 {idx}"))
        focus = str(item.get("focus") or analysis.get("summary") or "").strip()
        key_points = _as_list(item.get("key_points"))
        connections = _as_list(item.get("connections"))
        open_questions = _as_list(item.get("open_questions"))
        content = (
            f"# {title}\n\n"
            f"## 核心综合\n\n{focus or _bullet_list(key_points)}\n\n"
            f"## 关联知识\n\n{_bullet_list(connections or all_knowledge_names)}\n\n"
            f"## 易混点/对比\n\n{_bullet_list(key_points, '请对照相关概念、公式和原理理解它们的边界。')}\n\n"
            f"## 进一步问题\n\n{_bullet_list(open_questions or _as_list(analysis.get('knowledge_gaps')))}\n"
        )
        add_page("synthesis", title, content, ["synthesis", "imported"], [])

    for idx, item in enumerate(_as_list(analysis.get("q_and_a")), start=1):
        if not isinstance(item, dict):
            continue
        question = _clean_item_title(str(item.get("question") or f"关键问题 {idx}"))
        answer = str(item.get("answer") or "").strip()
        why = str(item.get("why_it_matters") or "").strip()
        related = _as_list(item.get("related_items"))
        title = question[:48] or f"关键问题 {idx}"
        content = (
            f"# {title}\n\n"
            f"## 问题\n\n{question}\n\n"
            f"## 回答\n\n{answer or '请结合来源文档中的定义、公式和原理回答。'}\n\n"
            f"## 为什么重要\n\n{why or '这个问题有助于检查是否真正理解文档的核心知识。'}\n\n"
            f"## 相关知识\n\n{_bullet_list(related or all_knowledge_names[:5])}\n"
        )
        add_page("query", title, content, ["qa", "imported"], [])

    for idx, item in enumerate(_as_list(analysis.get("system_notes")), start=1):
        if not isinstance(item, dict):
            continue
        title = _clean_item_title(str(item.get("title") or f"{source_relative_path} 学习指引 {idx}"))
        purpose = str(item.get("purpose") or "").strip()
        learning_order = _as_list(item.get("learning_order"))
        study_strategy = _as_list(item.get("study_strategy"))
        quality_warnings = _as_list(item.get("quality_warnings"))
        content = (
            f"# {title}\n\n"
            f"## 用途\n\n{purpose or f'整理 {source_relative_path} 的学习路径、复习方式和维护提醒。'}\n\n"
            f"## 推荐学习顺序\n\n{_bullet_list(learning_order or all_knowledge_names)}\n\n"
            f"## 复习策略\n\n{_bullet_list(study_strategy or exercise_names or ['先看概念和原理，再用练习检查理解。'])}\n\n"
            f"## 质量提醒\n\n{_bullet_list(quality_warnings or _as_list(analysis.get('review_items')) or ['如原文 OCR、公式或表格解析异常，请回到来源文档复核。'])}\n"
        )
        add_page("system", title, content, ["system", "imported"], [])

    has_educational_content = bool(concepts or formulas or principles or exercises)
    if has_educational_content and not any((p.get("page_type") == "synthesis") for p in normalized_pages):
        title = f"{source_relative_path} 综合学习图谱"
        content = (
            f"# {title}\n\n"
            f"## 核心综合\n\n{analysis.get('summary') or '本页综合导入文档中的核心知识结构。'}\n\n"
            f"## 关联知识\n\n{_bullet_list(all_knowledge_names)}\n\n"
            f"## 易混点/对比\n\n"
            f"{_bullet_list(_as_list(analysis.get('knowledge_gaps')), '重点比较概念、公式和原理之间的适用边界。')}\n\n"
            f"## 进一步问题\n\n{_bullet_list(_as_list(analysis.get('review_items')), '哪些公式可以用于解决哪些练习？哪些概念是后续内容的前提？')}\n"
        )
        add_page("synthesis", title, content, ["synthesis", "imported"], [])

    if has_educational_content and not any((p.get("page_type") == "query") for p in normalized_pages):
        title = f"{source_relative_path} 关键问答"
        content = (
            f"# {title}\n\n"
            f"## 问题\n\n这份文档最需要先理解什么？\n\n"
            f"## 回答\n\n需要先把核心概念、公式和原理串起来：{', '.join(all_knowledge_names[:6]) or '见来源摘要'}。\n\n"
            f"## 为什么重要\n\n这个问题能帮助学习者从被动阅读转向主动检索和自测。\n\n"
            f"## 相关知识\n\n{_bullet_list(all_knowledge_names[:6])}\n"
        )
        add_page("query", title, content, ["qa", "imported"], [])

    if has_educational_content and not any((p.get("page_type") == "system") for p in normalized_pages):
        title = f"{source_relative_path} 导入学习指引"
        content = (
            f"# {title}\n\n"
            f"## 用途\n\n为本次导入的文档建立学习顺序、复习方式和质量检查入口。\n\n"
            f"## 推荐学习顺序\n\n{_bullet_list(all_knowledge_names)}\n\n"
            f"## 复习策略\n\n{_bullet_list(exercise_names or ['阅读每个概念页后，回到对应公式、原理和练习进行自测。'])}\n\n"
            f"## 质量提醒\n\n{_bullet_list(_as_list(analysis.get('review_items')) or ['如果公式、表格或题目来自 OCR，请对照原始文档复核。'])}\n"
        )
        add_page("system", title, content, ["system", "imported"], [])

    return normalized_pages


def _analysis_is_empty(analysis: dict) -> bool:
    return not any(analysis.get(key) for key in ("concepts", "formulas", "principles", "exercises"))


def _fallback_analysis_from_text(content: str) -> dict:
    """Heuristic fallback when the LLM returns an empty analysis for clearly educational content."""
    text = re.sub(r"<[^>]+>", " ", content)
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line and not line.startswith("---")]

    concepts: list[dict] = []
    formulas: list[dict] = []
    principles: list[dict] = []
    exercises: list[dict] = []
    seen: dict[str, set[str]] = {"concept": set(), "formula": set(), "principle": set(), "exercise": set()}

    def add_concept(name: str, definition: str = ""):
        name = _clean_item_title(name)
        if _is_page_heading(name):
            return
        name = name.strip(" ：:，,。")
        if len(name) < 2 or len(name) > 30 or name in seen["concept"]:
            return
        seen["concept"].add(name)
        concepts.append({
            "name": name,
            "definition": definition or f"文档中出现的核心概念：{name}",
            "related_concepts": [],
            "parent_concept": "",
            "prerequisites": [],
        })

    def add_formula(name: str, latex: str, variables: str = ""):
        latex = _normalize_latex(latex)
        if not latex or "=" not in latex:
            return
        name = _clean_item_title(name)
        if _is_generic_formula_title(name):
            name = _formula_title_from_latex(latex, variables=variables, context=name)
        if len(name) < 2 or name in seen["formula"]:
            return
        seen["formula"].add(name)
        formulas.append({
            "name": name,
            "latex": latex,
            "variables": variables,
            "applications": f"用于分析{name}相关的材料电学性能。",
            "prerequisites": [],
        })

    def add_principle(name: str, statement: str = ""):
        name = _clean_item_title(name)
        if _is_page_heading(name):
            return
        name = name.strip(" ：:，,。")
        if len(name) < 2 or len(name) > 40 or name in seen["principle"]:
            return
        seen["principle"].add(name)
        principles.append({
            "name": name,
            "statement": statement or f"{name}是文档中涉及的重要规律或理论。",
            "conditions": "见原始文档上下文。",
            "derivation_summary": "",
            "applications": "用于解释材料电学性能。",
            "prerequisites": [],
        })

    def add_exercise(question: str):
        question = _clean_item_title(question)
        if _is_page_heading(question):
            return
        if len(question) < 6 or question in seen["exercise"]:
            return
        seen["exercise"].add(question)
        exercises.append({
            "question": question,
            "solution": "请结合文档中的定义、公式和图表进行分析。",
            "knowledge_points": [],
        })

    known_terms = [
        "导电", "电阻", "电阻率", "电导率", "导电机理", "霍耳效应", "霍尔效应",
        "霍耳系数", "霍尔系数", "经典自由电子理论", "量子自由电子理论", "能带理论",
        "费米能级", "费米分布函数", "导带", "价带", "禁带", "半导体", "绝缘体",
        "金属", "载流子浓度", "迁移率", "驰豫时间", "电子热导率",
    ]
    for term in known_terms:
        if term in content:
            add_concept(term)

    for i, line in enumerate(lines):
        if _is_page_heading(line):
            continue
        prev_line = lines[i - 1] if i > 0 else ""
        next_line = lines[i + 1] if i + 1 < len(lines) else ""

        clean_line = _clean_item_title(line)

        if re.search(r"(定律|理论|效应|规则|原理)", clean_line):
            add_principle(line, next_line if len(next_line) < 120 else "")

        if "?" in clean_line or "？" in clean_line or "为什么" in clean_line or "由什么决定" in clean_line:
            add_exercise(line)

        inline_formulas = re.findall(r"\$\s*([^$]{1,240}=[^$]{1,240})\s*\$", line)
        if inline_formulas:
            for formula in inline_formulas:
                add_formula(formula, formula)
            continue

        if (
            not re.search(r"[\u4e00-\u9fff]", line)
            and re.search(r"^[\s\w\\{}^_+\-*/().,，α-ωΑ-Ω𝑉𝐼𝑅𝜌𝜎𝜅𝜇𝜏𝐸𝐽𝐵=＝]+$", line)
            and re.search(r"[=＝]", line)
        ):
            name = prev_line if 2 <= len(_clean_item_title(prev_line)) <= 30 else line
            add_formula(name, line)

    summary = "文档包含材料电学性能相关知识，包括导电、电阻率、电导率、导电机理、霍耳效应、电子理论和能带理论等。"
    return {
        "summary": summary,
        "concepts": concepts[:30],
        "formulas": formulas[:20],
        "principles": principles[:15],
        "exercises": exercises[:10],
        "relationships": [],
        "knowledge_gaps": [],
        "review_items": ["LLM 分析为空，已使用规则兜底抽取；建议人工复核。"],
    }


def _augment_empty_analysis(analysis: dict, content: str) -> dict:
    if not isinstance(analysis, dict) or _analysis_is_empty(analysis):
        return _fallback_analysis_from_text(content)
    return analysis


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
        content, extracted_images, parse_method = await _parse_source_content(source_path, media_dir=media_dir)
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
        analysis = _augment_empty_analysis(await _load_llm_json(analysis_raw, expected="object"), content)
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
        pages = _ensure_pages_from_analysis(
            analysis,
            await _load_llm_json(gen_raw, expected="array"),
            source_relative_path,
        )
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

    generated_paths = [p["path"] for p in pages if p.get("path")]
    record_source_pages(source_relative_path, generated_paths + [source_summary_path], project_id=project_id)

    # Update index
    all_new = [{"path": p["path"], "title": p["title"], "type": p.get("page_type", "concept")}
               for p in pages]
    all_new.append({"path": source_summary_path, "title": source_relative_path, "type": "source"})
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
            content, extracted_images, parse_method = await _parse_source_content(source_path, media_dir=media_dir)
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
                        message=f"解析完成: {len(content):,} 字符 ({parse_method})" + (" (已截断)" if truncated else ""))

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
            analysis = _augment_empty_analysis(await _load_llm_json(analysis_raw, expected="object"), content)
        except Exception as e:
            yield await emit("error", source=source_relative_path, message=f"分析失败: {e}")
            continue

        # Report analysis findings in detail
        concepts_found = analysis.get("concepts", [])
        formulas_found = analysis.get("formulas", [])
        principles_found = analysis.get("principles", [])
        exercises_found = analysis.get("exercises", [])
        synthesis_found = analysis.get("synthesis", [])
        qa_found = analysis.get("q_and_a", [])
        system_found = analysis.get("system_notes", [])

        yield await emit("stage_done", source=source_relative_path,
                        stage="analyze",
                        message=f"分析完成: {len(concepts_found)} 个概念, {len(formulas_found)} 个公式, "
                                f"{len(principles_found)} 个原理, {len(exercises_found)} 个习题, "
                                f"{len(synthesis_found)} 个综合, {len(qa_found)} 个问答, {len(system_found)} 个系统指引",
                        details={
                            "concepts": [c.get("name", "") for c in concepts_found[:10]],
                            "formulas": [f.get("name", "") for f in formulas_found[:5]],
                            "principles": [p.get("name", "") for p in principles_found[:5]],
                            "exercises": [e.get("question", "")[:40] for e in exercises_found[:5]],
                            "synthesis": [s.get("title", "") for s in synthesis_found[:5]],
                            "q_and_a": [q.get("question", "")[:40] for q in qa_found[:5]],
                            "system_notes": [s.get("title", "") for s in system_found[:5]],
                        })

        # Step 2: Generation
        yield await emit("stage", source=source_relative_path,
                        stage="generate",
                        message=f"Step 2/2: LLM 正在生成 Wiki 页面..."
                              f"({len(concepts_found)} 概念 + {len(formulas_found)} 公式 "
                              f"+ {len(principles_found)} 原理 + {len(exercises_found)} 习题 "
                              f"+ {len(synthesis_found)} 综合 + {len(qa_found)} 问答 + {len(system_found)} 系统)")
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
            pages = _ensure_pages_from_analysis(
                analysis,
                await _load_llm_json(gen_raw, expected="array"),
                source_relative_path,
            )
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

        generated_paths = [p["path"] for p in pages if p.get("path")]
        record_source_pages(source_relative_path, generated_paths + [source_summary_path], project_id=project_id)

        # Update index
        all_new = [{"path": p["path"], "title": p["title"], "type": p.get("page_type", "concept")}
                   for p in pages]
        all_new.append({"path": source_summary_path, "title": source_relative_path, "type": "source"})
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
        content, extracted_images, parse_method = await _parse_source_content(source_path, media_dir=media_dir)
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
               message=f"解析完成: {len(content):,} 字符 ({parse_method})" + (" (已截断)" if truncated else ""))

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
        analysis = _augment_empty_analysis(await _load_llm_json(analysis_raw, expected="object"), content)
    except Exception as e:
        await emit("error", source=source_relative_path, message=f"分析失败: {e}")
        return

    concepts_found = analysis.get("concepts", [])
    formulas_found = analysis.get("formulas", [])
    principles_found = analysis.get("principles", [])
    exercises_found = analysis.get("exercises", [])
    synthesis_found = analysis.get("synthesis", [])
    qa_found = analysis.get("q_and_a", [])
    system_found = analysis.get("system_notes", [])

    await emit("stage_done", source=source_relative_path,
               stage="analyze",
               message=f"分析完成: {len(concepts_found)} 个概念, {len(formulas_found)} 个公式, "
                       f"{len(principles_found)} 个原理, {len(exercises_found)} 个习题, "
                       f"{len(synthesis_found)} 个综合, {len(qa_found)} 个问答, {len(system_found)} 个系统指引",
               details={
                   "concepts": [c.get("name", "") for c in concepts_found[:10]],
                   "formulas": [f.get("name", "") for f in formulas_found[:5]],
                   "principles": [p.get("name", "") for p in principles_found[:5]],
                   "exercises": [e.get("question", "")[:40] for e in exercises_found[:5]],
                   "synthesis": [s.get("title", "") for s in synthesis_found[:5]],
                   "q_and_a": [q.get("question", "")[:40] for q in qa_found[:5]],
                   "system_notes": [s.get("title", "") for s in system_found[:5]],
               })

    # Step 2: Generation
    await emit("stage", source=source_relative_path,
               stage="generate",
               message=f"Step 2/2: LLM 正在生成 Wiki 页面..."
                       f"({len(concepts_found)} 概念 + {len(formulas_found)} 公式 "
                       f"+ {len(principles_found)} 原理 + {len(exercises_found)} 习题 "
                       f"+ {len(synthesis_found)} 综合 + {len(qa_found)} 问答 + {len(system_found)} 系统)")
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
        pages = _ensure_pages_from_analysis(
            analysis,
            await _load_llm_json(gen_raw, expected="array"),
            source_relative_path,
        )
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

    generated_paths = [p["path"] for p in pages if p.get("path")]
    record_source_pages(source_relative_path, generated_paths + [source_summary_path], project_id=project_id)

    # Update index
    all_new = [{"path": p["path"], "title": p["title"], "type": p.get("page_type", "concept")}
               for p in pages]
    all_new.append({"path": source_summary_path, "title": source_relative_path, "type": "source"})
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
