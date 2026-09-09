"""Multi-stage educational wiki ingest engine.

Stage 1: plan source summary and core concept/formula/principle pages.
Stage 2: generate the core wiki pages.
Stage 3: derive synthesis, Q&A, and study-guide structures from the core pages.
Stage 4: assemble, validate, write, index, and sync generated wiki pages.

Supports concurrent processing with configurable concurrency limit.
"""

import asyncio
import json
import re
from pathlib import Path

from services.file_parser import parse_file
from services.language import language_instruction
from services.llm_client import chat_complete, stream_chat
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



CORE_PLANNING_PROMPT = """You are an expert educational planner. Your task is to analyze a parsed source document and produce a structured **core page plan** covering ALL FIVE A-stage page types: source, concept, formula, principle, procedure. Output a single JSON object the downstream wiki writer will use.

## Source
- title: {source_title}
- total_pages: {page_count}

## Parsed pages (truncated to {max_chars} chars)
{content}

## Output schema (JSON object)
For each **concept**:
- "name": concept name (short, 2-8 字). Definition, glossary term, or named idea.
- "definition": one-sentence definition in the output language (cite "p.5" for page number)
- "related": list of other concept names from this plan
- "page_refs": integer pages where this concept is defined or explained (1-indexed)

For each **formula**:
- "name": human-readable formula name (NOT raw equation)
- "latex": the LaTeX equation, $...$ delimiters optional
- "variables": brief description of each variable
- "applications": one-sentence note on when to use
- "page_refs": integer pages

For each **principle**:
- "name": principle name
- "statement": one-sentence core claim
- "conditions": when this principle applies
- "page_refs": integer pages

For each **procedure**:
- "name": procedure name
- "goal": one-sentence outcome
- "input": what the procedure takes
- "output": what it produces
- "page_refs": integer pages

"source" entry:
- "summary": 2-3 sentence summary in the output language
- "topic_tags": list of 3-6 keyword tags
- "page_count_estimate": integer

CRITICAL RULES:
1. Cover at least 2-3 items per type (if the document supports it). Empty arrays are allowed ONLY for types that genuinely have no content in the source.
2. Use ONLY pages that appear in the source. Do not invent page numbers; omit page_refs if unsure.
3. Output a SINGLE JSON object with these top-level keys: source, concepts, formulas, principles, procedures. No markdown fences, no commentary.

## Output Language
{language_instruction}
"""


CORE_PAGE_GENERATION_PROMPT = """You are an expert educational wiki writer. Your task is to generate only the core wiki pages from an approved page plan.

## Core Page Plan
{plan}

## Purpose (Educational Goals)
{purpose}

## Schema (Page Structure Rules)
{schema}

## Output Language
{language_instruction}

## Instructions
Generate wiki pages only for the A-stage (core) page types in the plan: source, concept, formula, principle, procedure. Do NOT create example, misconception, synthesis, learning_path, learning_objective, or rubric pages in this stage — those are generated on demand from later stages.

For each page, output a JSON object with:
- path: relative path within wiki/ (e.g., "concepts/quantum_state.md")
- title: page title
- page_type: source | concept | formula | principle | procedure
- frontmatter (all keys required, no omissions):
  - sources: list of source file references this page draws on
  - tags: list of relevant tags (use lowercase, hyphenated for multi-word)
  - prerequisites: list of page paths that must be understood before this page (only paths that exist in the plan or current wiki)
  - related: list of page paths that this page connects to (sibling concepts, see-also)
  - common_misconceptions: list of concise strings naming what learners commonly get wrong about this page
  - worked_example_ref: list of page paths that are worked examples for this content
  - difficulty: integer 1-5 (1 = introductory recall, 5 = requires synthesis or advanced application)
  - last_reviewed: ISO 8601 datetime stamp set to the current generation moment (do not invent historical dates)
- content: full markdown body with [[wikilinks]] to other wiki pages and $...$ inline LaTeX for math

Page rules:
- Concept pages should define, explain, and connect the concept to related core pages.
- Formula pages must contain sections "## 公式", "## 变量说明", and "## 适用场景".
- Principle pages must contain sections "## 陈述", "## 适用条件", "## 推导/说明", and "## 应用".
- Procedure pages must contain sections "## 目标", "## 输入", "## 输出", "## 步骤", "## 检查清单".
- Source pages summarize the source file structure and list candidate citations.
- Formula titles must be semantic human-readable names, not raw equations.
- Do not invent new knowledge not supported by the plan.
- Use [[page/path]] links only for pages that are in the plan or existing wiki context.
- All math should use lightweight inline LaTeX delimiters $...$; do not force double-dollar display blocks.

### Citation marker (REQUIRED for every non-trivial claim)
Every substantive sentence that draws from the source MUST end with an inline citation marker in this exact form:
  [ref:<filename>#p=N]
where <filename> is the source file's exact name (e.g. "第三章第四节.pdf") and N is the page number.
- If a sentence is grounded in multiple pages of the same file, use a comma-separated page list:
  [ref:第三章第四节.pdf#p=5, 8]
- If a sentence cites multiple files, write a separate marker after the sentence for each file.
- Do NOT invent page numbers. If you are not certain, omit the marker.
- Definitions, principle statements, formula applicability conditions, and procedure step goals all require markers.
- Do not put markers inside math expressions or code blocks.

Return a JSON array of page objects.
CRITICAL: Output ONLY the JSON array, no markdown fences or explanation.
"""

DERIVED_LEARNING_PROMPT = """You are an expert educational designer. Your task is to create advanced learning materials from already planned/generated core wiki pages.

## Core Page Plan
{plan}

## Generated Core Pages
{core_pages}

## Output Language
{language_instruction}

## Instructions
Create derived learning structures from the core concept/formula/principle pages. Do not add new core knowledge pages, and do not generate exercises — exercises are produced on demand from the Tests view, not at import time.

Output a JSON object with this shape:

```json
{{
  "synthesis": [
    {{
      "title": "Synthesis page title",
      "focus": "What cross-page understanding this helps build",
      "key_points": ["comparison, connection, or misconception"],
      "connections": ["titles of existing core pages"],
      "open_questions": ["follow-up questions or limitations"]
    }}
  ],
  "inquiry": [
    {{
      "title": "Inquiry page title",
      "thesis": "A high-value learner question phrased as a one-line thesis",
      "perspectives": ["distinct angle or sub-question that the inquiry should cover"],
      "answer": "Clear answer grounded in existing core pages",
      "why_it_matters": "Why this question is useful",
      "related_items": ["titles of existing core pages"]
    }}
  ],
  "guide": [
    {{
      "title": "Learning/navigation guide title",
      "purpose": "How this note improves learning or wiki maintenance",
      "learning_order": ["ordered titles of existing core pages"],
      "review_strategies": ["specific review action a learner can take"],
      "quality_warnings": ["things to verify against the source"]
    }}
  ]
}}
```

Naming note: the key `inquiry` supersedes the legacy `q_and_a`; the key `guide` supersedes the legacy `system_notes`. Use the new keys in your output.

Return a single JSON object.
CRITICAL: Output ONLY the JSON object, no markdown fences or explanation.
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
        # A 组基础页（import 时生成）
        "concept": "concepts",
        "formula": "formulas",
        "principle": "principles",
        "procedure": "procedures",
        # B 组应用页（按需生成）
        "example": "examples",
        "misconception": "misconceptions",
        # C 组整合 / 评价页（按需生成）
        "synthesis": "synthesis",
        "learning_path": "learning_paths",
        "learning_objective": "objectives",
        "rubric": "rubrics",
        # 源页（A 组 0 号）
        "source": "sources",
        # v2 历史 / 兼容
        "inquiry": "inquiries",
        "guide": "guides",
    }
    folder = folder_by_type.get(page_type, f"{page_type}s")
    return f"{folder}/{_slugify_title(title)}.md"


# Stage 分组常量 — 跟前端 lib/page-type.tsx 的 STAGE_GROUPS 对齐
A_STAGE_TYPES = ("source", "concept", "principle", "formula", "procedure")
B_STAGE_TYPES = ("example", "misconception")
C_STAGE_TYPES = ("synthesis", "learning_path", "learning_objective", "rubric")
ALL_PAGE_TYPES = A_STAGE_TYPES + B_STAGE_TYPES + C_STAGE_TYPES


def _as_list(value) -> list:
    return value if isinstance(value, list) else []


def _bullet_list(items: list, fallback: str = "待补充") -> str:
    clean = [str(item).strip() for item in items if str(item).strip()]
    return "\n".join(f"- {item}" for item in clean) if clean else fallback


def _prefer_inline_math(content: str) -> str:
    """Normalize display math blocks to lightweight inline math."""
    def replace_block(match: re.Match) -> str:
        inner = re.sub(r"\s+", " ", match.group(1)).strip()
        return f"${inner}$"

    return re.sub(r"\$\$\s*(.*?)\s*\$\$", replace_block, content, flags=re.DOTALL)


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
            page["content"] = _prefer_inline_math(content)
        page.setdefault("sources", [source_relative_path])
        # 容错: LLM 常用 (p.N) 代替 [ref:…]，自动转
        page["content"] = _convert_inline_citations(
            str(page.get("content") or ""), source_relative_path
        )
        normalized.append(page)
    return normalized


def _convert_inline_citations(content: str, source_filename: str) -> str:
    """把 LLM 写的'(p.N)'、'（p.N）'等内联引用转成 [ref:file#p=N] 格式。

    LLM 抽风时常用人类可读格式而非严格语法。本函数是 LLM 输出的容错层。
    """
    if not content:
        return content
    src_file = source_filename.rsplit("/", 1)[-1]

    def _repl(m: re.Match) -> str:
        nums = [int(x.strip()) for x in m.group(1).split(",") if x.strip().isdigit()]
        if not nums:
            return m.group(0)
        return f"[ref:{src_file}#p={','.join(str(n) for n in nums)}]"

    return INLINE_PAGE_REF_RE.sub(_repl, content)


# Stage 3 — citation 校验：扫 [ref:file#p=N, ...] 标号，用 parsed.json 反查 quote offset
# --------------------------------------------------------------------------------------

CITE_REF_TOKEN_RE = re.compile(r"\[ref:([^\]\|#]+)#p=([\d,\s]+)\]")

# 容错: LLM 不一定遵守 [ref:…] 语法，常写成"（p.1）" / "(p.2)" / "（p.3, 5）"等。
# 这些是 LLM 输出的"想表达引用但格式不对"的情况，我们在 verify 之前自动转。
INLINE_PAGE_REF_RE = re.compile(
    r"[（(]\s*p\.?\s*([0-9,\s]+)\s*[）)]",  # 兼容中英括号 + 可选 p./P. 前缀
    re.IGNORECASE,
)


def _extract_cite_refs(content: str) -> list[dict]:
    """返回 [{file, page, quote, ...}] 列表，每个 (file, page) 唯一。

    quote 取标号前最近的一句（不超过 60 字符）作为回查用。
    """
    out: list[dict] = []
    seen: set[tuple[str, int]] = set()
    for m in CITE_REF_TOKEN_RE.finditer(content):
        file = m.group(1).strip()
        pages = [int(p.strip()) for p in m.group(2).split(",") if p.strip().isdigit()]
        # 抓该标号之前的最近一个完整句（"。" 或换行），最多 60 字
        start = max(0, m.start() - 60)
        head = content[start:m.start()]
        last_punct = max(head.rfind("。"), head.rfind(".\n"), head.rfind("\n"))
        quote = head[last_punct + 1 :].strip() if last_punct != -1 else head.strip()
        quote = quote[:60]
        for p in pages:
            key = (file, p)
            if key in seen:
                continue
            seen.add(key)
            out.append({"file": file, "page": p, "quote": quote})
    return out


def _verify_cite_refs(pages: list[dict], project_id: str) -> None:
    """Stage 3 校验：把 verified / offset_start / offset_end 写进 page frontmatter。

    parsed.json 由 build_parsed_index 在 import 阶段（或请求时）落盘。
    """
    from services.parsed_index import load_parsed_index
    from storage.wiki_store import sources_path

    sp = sources_path(project_id)
    # 按 file 缓存 parsed.json，避免一页校验多 ref 时反复读盘
    parsed_cache: dict[str, dict | None] = {}

    for page in pages:
        refs = _extract_cite_refs(str(page.get("content") or ""))
        if not refs:
            page.setdefault("source_refs", [])
            page.setdefault("unverified_refs", [])
            continue
        verified: list[dict] = []
        unverified: list[dict] = []
        for r in refs:
            if r["file"] not in parsed_cache:
                # source_filename 形如 "第三章第四节.pdf"，但 parsed 目录用相对路径的 base 名
                parsed_cache[r["file"]] = load_parsed_index(sp, r["file"])
            parsed = parsed_cache[r["file"]]
            if not parsed:
                unverified.append(r)
                continue
            # 在该页 md 里反查 quote
            from services.parsed_index import find_quote
            offsets = find_quote(parsed, r["page"], r["quote"])
            if offsets:
                r["verified"] = True
                r["offset_start"] = offsets[0][0]
                r["offset_end"] = offsets[0][1]
                verified.append(r)
            else:
                r["verified"] = False
                unverified.append(r)
        page["source_refs"] = verified
        page["unverified_refs"] = unverified


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

    def add_page(
        page_type: str,
        title: str,
        content: str,
        tags: list[str],
        prerequisites: list[str] | None = None,
        related: list[str] | None = None,
    ):
        key = (page_type, title.strip().lower())
        if not title or key in existing:
            return
        existing.add(key)
        # 如果 core_pages 里有同 title 的 LLM 长文，优先用它的 content（带 [ref:…]）
        merged_content = content
        for cp in normalized_pages:
            if (
                (cp.get("page_type") or "concept") == page_type
                and (cp.get("title") or "").strip().lower() == title.strip().lower()
                and cp.get("content")
            ):
                merged_content = cp["content"]
                merged_tags = list({*(cp.get("tags") or []), *tags})
                break
        else:
            merged_tags = tags
        normalized_pages.append({
            "path": _page_path_for(page_type, title),
            "title": title,
            "page_type": page_type,
            "content": merged_content,
            "sources": [source_relative_path],
            "tags": merged_tags,
            "prerequisites": prerequisites or [],
            "related": related or [],
        })

    for item in analysis.get("concepts", []) or []:
        if not isinstance(item, dict):
            continue
        title = _clean_item_title(str(item.get("name") or item.get("title") or ""))
        if not title:
            continue
        definition = str(item.get("definition") or item.get("description") or "").strip()
        related = item.get("related_concepts") if isinstance(item.get("related_concepts"), list) else []
        parent = str(item.get("parent_concept") or "").strip()
        prereqs = item.get("prerequisites") if isinstance(item.get("prerequisites"), list) else []
        content = (
            f"# {title}\n\n"
            f"## 定义\n\n{definition or f'{title} 是来源文档中需要掌握的核心概念。'}\n\n"
            f"## 上位概念\n\n{parent or '待补充'}\n\n"
            f"## 相关概念\n\n{_bullet_list(related, '待补充')}\n"
        )
        add_page("concept", title, content, ["concept"], prereqs, related)

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
            f"## 公式\n\n${latex}$\n\n"
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

    concepts = _as_list(analysis.get("concepts"))
    formulas = _as_list(analysis.get("formulas"))
    principles = _as_list(analysis.get("principles"))
    concept_names = _names_from_items(concepts)
    formula_names = _formula_names_from_items(formulas)
    principle_names = _names_from_items(principles)
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
        add_page("synthesis", title, content, ["synthesis", "imported"], [], connections or all_knowledge_names)

    for idx, item in enumerate(_as_list(analysis.get("inquiry")), start=1):
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
        add_page("inquiry", title, content, ["qa", "imported"], [], related or all_knowledge_names[:5])

    for idx, item in enumerate(_as_list(analysis.get("guide")), start=1):
        if not isinstance(item, dict):
            continue
        title = _clean_item_title(str(item.get("title") or f"{source_relative_path} 学习指引 {idx}"))
        purpose = str(item.get("purpose") or "").strip()
        learning_order = _as_list(item.get("learning_order"))
        # New prompt uses `review_strategies`; legacy `study_strategy` is still
        # accepted so older analyses keep rendering.
        review_strategies = _as_list(item.get("review_strategies")) or _as_list(item.get("study_strategy"))
        quality_warnings = _as_list(item.get("quality_warnings"))
        content = (
            f"# {title}\n\n"
            f"## 用途\n\n{purpose or f'整理 {source_relative_path} 的学习路径、复习方式和维护提醒。'}\n\n"
            f"## 推荐学习顺序\n\n{_bullet_list(learning_order or all_knowledge_names)}\n\n"
            f"## 复习策略\n\n{_bullet_list(review_strategies or ['先看概念和原理；如需练习，到 Tests 视图按范围生成测试题。'])}\n\n"
            f"## 质量提醒\n\n{_bullet_list(quality_warnings or _as_list(analysis.get('review_items')) or ['如原文 OCR、公式或表格解析异常，请回到来源文档复核。'])}\n"
        )
        add_page("guide", title, content, ["guide", "imported"], [], learning_order or all_knowledge_names)

    has_educational_content = bool(concepts or formulas or principles)
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
        add_page("synthesis", title, content, ["synthesis", "imported"], [], connections or all_knowledge_names)

    if has_educational_content and not any((p.get("page_type") == "inquiry") for p in normalized_pages):
        title = f"{source_relative_path} 关键问答"
        content = (
            f"# {title}\n\n"
            f"## 问题\n\n这份文档最需要先理解什么？\n\n"
            f"## 回答\n\n需要先把核心概念、公式和原理串起来：{', '.join(all_knowledge_names[:6]) or '见来源摘要'}。\n\n"
            f"## 为什么重要\n\n这个问题能帮助学习者从被动阅读转向主动检索和自测。\n\n"
            f"## 相关知识\n\n{_bullet_list(all_knowledge_names[:6])}\n"
        )
        add_page("inquiry", title, content, ["qa", "imported"], [], related or all_knowledge_names[:5])

    if has_educational_content and not any((p.get("page_type") == "guide") for p in normalized_pages):
        title = f"{source_relative_path} 导入学习指引"
        content = (
            f"# {title}\n\n"
            f"## 用途\n\n为本次导入的文档建立学习顺序、复习方式和质量检查入口。\n\n"
            f"## 推荐学习顺序\n\n{_bullet_list(all_knowledge_names)}\n\n"
            f"## 复习策略\n\n{_bullet_list(['阅读每个概念页后，回到对应公式和原理进行自测。', '如需练习，到 Tests 视图按范围生成测试题。'])}\n\n"
            f"## 质量提醒\n\n{_bullet_list(_as_list(analysis.get('review_items')) or ['如果公式或表格来自 OCR，请对照原始文档复核。'])}\n"
        )
        add_page("guide", title, content, ["guide", "imported"], [], learning_order or all_knowledge_names)

    return normalized_pages


def _analysis_is_empty(analysis: dict) -> bool:
    return not any(analysis.get(key) for key in ("concepts", "formulas", "principles"))


async def _generate_core_plan_llm(
    content: str,
    source_title: str,
    page_count: int,
    *,
    project_id: str = "default",
    emit=None,
    source_relative_path: str = "",
) -> dict:
    """Step 1/4: 用 LLM 把 parsed document.md 规划成 A 组 5 类候选。

    Returns dict with keys: source, concepts, formulas, principles, procedures.
    On any error returns {} (caller will fall back to heuristic).
    """
    from services.language import language_instruction as _li

    # 截断到 ~24k 字符，给 LLM 留余量生成完整 JSON
    max_chars = 24_000
    snippet = content if len(content) <= max_chars else content[:max_chars] + "\n\n[... truncated ...]"

    user_prompt = CORE_PLANNING_PROMPT.format(
        source_title=source_title,
        page_count=page_count,
        max_chars=max_chars,
        content=snippet,
        language_instruction=_li(),
    )
    raw = await _chat_complete_progress(
        system_prompt="You are an expert educational planner. Output ONLY valid JSON.",
        user_prompt=user_prompt,
        temperature=0.25,
        max_tokens=8192,
        emit=emit,
        source=source_relative_path,
        stage="plan",
    )
    try:
        plan = await _load_llm_json(raw, expected="object")
    except Exception:
        return {}
    if not isinstance(plan, dict):
        return {}
    return plan


def _llm_plan_to_core_plan(plan: dict, source_title: str, page_count: int = 0) -> dict:
    """把 LLM 的 5 类规划 normalize 成 ingest engine 用的 core_plan。

    core_plan 历史上用 _knowledge_counts() 数 {concepts, formulas, principles, synthesis, inquiry, guide}。
    5 类 A 组里 synthesis/inquiry/guide 是 C 组，不在 plan 里——初始化为空。
    """
    source = plan.get("source") or {}
    return {
        "summary": source.get("summary", "") or f"文档：{source_title}",
        "tags": source.get("topic_tags", []) or [],
        "concepts": plan.get("concepts", []) or [],
        "formulas": plan.get("formulas", []) or [],
        "principles": plan.get("principles", []) or [],
        "procedures": plan.get("procedures", []) or [],
        # C 组 — planning 阶段不规划，按需生成
        "synthesis": [],
        "inquiry": [],
        "guide": [],
        # 元信息
        "page_count_estimate": source.get("page_count_estimate", page_count),
        "planning_source": "llm",
    }


def _fallback_analysis_from_text(content: str) -> dict:
    """Heuristic fallback when the LLM returns an empty analysis for clearly educational content."""
    text = re.sub(r"<[^>]+>", " ", content)
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line and not line.startswith("---")]

    concepts: list[dict] = []
    formulas: list[dict] = []
    principles: list[dict] = []
    seen: dict[str, set[str]] = {"concept": set(), "formula": set(), "principle": set()}

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


async def _emit_optional(emit, event: str, **kwargs):
    if emit:
        await emit(event, **kwargs)


async def _chat_complete_progress(
    *,
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    max_tokens: int,
    emit=None,
    source: str = "",
    stage: str = "",
) -> str:
    chunks: list[str] = []
    async for chunk in stream_chat(
        system_prompt=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
        temperature=temperature,
        max_tokens=max_tokens,
    ):
        chunks.append(chunk)
        await _emit_optional(emit, "llm_delta", source=source, stage=stage, text=chunk)
    return "".join(chunks)


def _knowledge_counts(analysis: dict) -> dict[str, int]:
    return {
        "concepts": len(_as_list(analysis.get("concepts"))),
        "formulas": len(_as_list(analysis.get("formulas"))),
        "principles": len(_as_list(analysis.get("principles"))),
        "synthesis": len(_as_list(analysis.get("synthesis"))),
        "inquiry": len(_as_list(analysis.get("inquiry"))),
        "guide": len(_as_list(analysis.get("guide"))),
    }


def _analysis_details(analysis: dict) -> dict:
    return {
        "concepts": [c.get("name", "") for c in _as_list(analysis.get("concepts"))[:10] if isinstance(c, dict)],
        "formulas": [f.get("name", "") for f in _as_list(analysis.get("formulas"))[:5] if isinstance(f, dict)],
        "principles": [p.get("name", "") for p in _as_list(analysis.get("principles"))[:5] if isinstance(p, dict)],
        "synthesis": [s.get("title", "") for s in _as_list(analysis.get("synthesis"))[:5] if isinstance(s, dict)],
        "inquiry": [q.get("thesis", q.get("question", ""))[:40] for q in _as_list(analysis.get("inquiry"))[:5] if isinstance(q, dict)],
        "guide": [s.get("title", "") for s in _as_list(analysis.get("guide"))[:5] if isinstance(s, dict)],
    }


def _merge_derived_analysis(core_plan: dict, derived: object) -> dict:
    analysis = dict(core_plan)
    if isinstance(derived, dict):
        for key in ("synthesis", "inquiry", "guide"):
            analysis[key] = _as_list(derived.get(key))
    else:
        for key in ("synthesis", "inquiry", "guide"):
            analysis.setdefault(key, [])
    return analysis


async def _generate_core_pages(core_plan: dict, *, project_id: str, source_relative_path: str, emit=None) -> list[dict]:
    wp = wiki_path(project_id)
    purpose_path = wp / "purpose.md"
    schema_path = wp / "schema.md"
    purpose_text = purpose_path.read_text(encoding="utf-8")[:3000] if purpose_path.exists() else "Not defined yet"
    schema_text = schema_path.read_text(encoding="utf-8")[:3000] if schema_path.exists() else "Not defined yet"

    raw = await _chat_complete_progress(
        system_prompt="You are an expert educational wiki writer. Output ONLY valid JSON array.",
        user_prompt=CORE_PAGE_GENERATION_PROMPT.format(
            plan=json.dumps(core_plan, ensure_ascii=False, indent=2),
            purpose=purpose_text,
            schema=schema_text,
            language_instruction=language_instruction(),
        ),
        temperature=0.25,
        max_tokens=8192,
        emit=emit,
        source=source_relative_path,
        stage="generate_core",
    )
    return _ensure_pages_from_analysis(
        core_plan,
        await _load_llm_json(raw, expected="array"),
        source_relative_path,
    )


async def _generate_derived_analysis(core_plan: dict, core_pages: list[dict], *, emit=None, source_relative_path: str = "") -> dict:
    core_page_summaries = [
        {
            "path": page.get("path"),
            "title": page.get("title"),
            "page_type": page.get("page_type"),
            "content": str(page.get("content") or "")[:1200],
        }
        for page in core_pages
        if page.get("page_type") in {"concept", "formula", "principle"}
    ]
    raw = await _chat_complete_progress(
        system_prompt="You are an expert educational designer. Output ONLY valid JSON.",
        user_prompt=DERIVED_LEARNING_PROMPT.format(
            plan=json.dumps(core_plan, ensure_ascii=False, indent=2),
            core_pages=json.dumps(core_page_summaries, ensure_ascii=False, indent=2),
            language_instruction=language_instruction(),
        ),
        temperature=0.35,
        max_tokens=8192,
        emit=emit,
        source=source_relative_path,
        stage="derive",
    )
    return await _load_llm_json(raw, expected="object")


# --------------------------------------------------------------------------------------
# B / C 阶段：按需触发，独立函数
# --------------------------------------------------------------------------------------

B_STAGE_PROMPT = """You are an expert educational wiki writer. Generate B-stage (applied) wiki pages from an existing core wiki page.

## Anchor Page
{anchor}

## Source file (parsed)
{source_summary}

## Requested page types
{page_types}

## Extra context
{extra_context}

## Schema
Each page is a JSON object with:
- path: relative path within wiki/ (e.g. "examples/foo.md")
- title: page title
- page_type: example | misconception
- content: full markdown body, with sections:
    - example → "## 题目", "## 步骤", "## 答案", "## 变式"
    - misconception → "## 错误说法", "## 正确理解", "## 诊断题"
- frontmatter (all keys required):
    - sources, tags, prerequisites, related, difficulty, last_reviewed
- INCLUDE inline citations: whenever a sentence is grounded in a specific page of the source, append a marker `[ref:<source_filename>#p=<page>]` (multiple sources: comma-separated within one `[ref:...]` block). Do NOT invent page numbers; omit the marker if unsure. Multi-page same file is allowed: `[ref:file.pdf#p=5, 8]`.

## Output
Return a JSON array of page objects. CRITICAL: Output ONLY the JSON array, no fences or explanation.
"""


async def _generate_b_stage_pages(
    anchor_page: dict,
    *,
    page_types: list[str],
    source_file: str,
    extra_context: str = "",
    project_id: str = "default",
    emit=None,
) -> list[dict]:
    """按需生成 B 组应用页。anchor_page 是触发页（已存在的 A 组页）。"""
    from storage.wiki_store import read_wiki_page

    pages: list[dict] = []
    for ptype in page_types:
        if ptype not in B_STAGE_TYPES:
            continue
        # 给 LLM 一个精简的源页摘要，避免 prompt 爆炸
        try:
            parsed = load_parsed_index(sources_path(project_id), source_file)
        except Exception:
            parsed = None
        if parsed and parsed.get("pages"):
            # 找 anchor_page 提到的页 + 邻居几页作上下文
            source_summary = "\n\n---\n\n".join(
                p["md"][:600] for p in parsed["pages"][:3]
            )
        else:
            source_summary = "(未解析的源文件)"

        user_prompt = B_STAGE_PROMPT.format(
            anchor=json.dumps({
                "path": anchor_page.get("path"),
                "title": anchor_page.get("title"),
                "page_type": anchor_page.get("page_type"),
                "content": str(anchor_page.get("content") or "")[:1500],
            }, ensure_ascii=False, indent=2),
            source_summary=source_summary[:4000],
            page_types=ptype,
            extra_context=extra_context or "(无)",
            language_instruction=language_instruction(),
        )
        raw = await _chat_complete_progress(
            system_prompt="You are an expert educational wiki writer. Output ONLY valid JSON.",
            user_prompt=user_prompt,
            temperature=0.3,
            max_tokens=4096,
            emit=emit,
            source=source_file,
            stage=f"b_stage_{ptype}",
        )
        try:
            arr = await _load_llm_json(raw, expected="array")
        except Exception:
            arr = []
        if isinstance(arr, list):
            for p in arr:
                if isinstance(p, dict):
                    p.setdefault("page_type", ptype)
                    p.setdefault("sources", [source_file])
                    pages.append(p)
    return pages


C_STAGE_PROMPT = """You are an expert educational designer. Generate a single C-stage wiki page from the provided context.

## Page type
{page_type}

## Target pages (anchor content)
{targets}

## Source files (parsed excerpts)
{sources}

## Extra context
{extra_context}

## Schema
- path, title, page_type ∈ {synthesis, learning_path, learning_objective, rubric}
- content: full markdown body, with sections:
    - synthesis → "## 综合论点", "## 关联知识" (use [[wikilinks]])
    - learning_path → "## 先修知识", "## 推荐顺序", "## 检测点" (use [[wikilinks]])
    - learning_objective → "## 行为动词", "## 认知层级", "## 达成证据"
    - rubric → "## 掌握等级", "## 表现描述", "## 评分规则"
- frontmatter (all keys required)
- INCLUDE inline citations `[ref:<file>#p=<page>]` ONLY for synthesis pages. For other C types, omit citations.

## Output
Return ONE JSON object. CRITICAL: Output ONLY the JSON object, no fences or explanation.
"""


async def _generate_c_stage_page(
    *,
    page_type: str,
    target_pages: list[dict],
    source_files: list[str],
    extra_context: str = "",
    project_id: str = "default",
    emit=None,
) -> dict | None:
    """按需生成 C 组整合 / 评价页。"""
    if page_type not in C_STAGE_TYPES:
        return None
    sp = sources_path(project_id)
    source_excerpts: list[str] = []
    for src in source_files:
        parsed = load_parsed_index(sp, src)
        if parsed and parsed.get("pages"):
            source_excerpts.append(
                f"### {src}\n\n" + "\n\n---\n\n".join(p["md"][:400] for p in parsed["pages"][:3])
            )
    sources_text = "\n\n".join(source_excerpts)[:5000] or "(未提供源文件)"

    user_prompt = C_STAGE_PROMPT.format(
        page_type=page_type,
        targets=json.dumps(
            [{"path": t.get("path"), "title": t.get("title"),
              "page_type": t.get("page_type"),
              "content": str(t.get("content") or "")[:1200]}
             for t in target_pages],
            ensure_ascii=False, indent=2,
        ),
        sources=sources_text,
        extra_context=extra_context or "(无)",
        language_instruction=language_instruction(),
    )
    raw = await _chat_complete_progress(
        system_prompt="You are an expert educational designer. Output ONLY valid JSON.",
        user_prompt=user_prompt,
        temperature=0.3,
        max_tokens=4096,
        emit=emit,
        source=(source_files[0] if source_files else ""),
        stage=f"c_stage_{page_type}",
    )
    try:
        obj = await _load_llm_json(raw, expected="object")
    except Exception:
        return None
    if isinstance(obj, dict):
        obj.setdefault("page_type", page_type)
        if not obj.get("sources"):
            obj["sources"] = list(source_files)
        return obj
    return None


def _write_ingest_outputs(
    pages: list[dict],
    analysis: dict,
    source_relative_path: str,
    *,
    project_id: str,
) -> dict:
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
                related=page.get("related", []),
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

    all_new = [{"path": p["path"], "title": p["title"], "type": p.get("page_type", "concept")}
               for p in pages]
    all_new.append({"path": source_summary_path, "title": source_relative_path, "type": "source"})
    update_index(all_new, project_id=project_id)

    _sync_vectors(pages, project_id=project_id)

    return {
        "created": created,
        "updated": updated,
        "concepts": concepts,
        "source_summary_path": source_summary_path,
    }


async def _run_ingest_pipeline(source_relative_path: str, force: bool = False, *, project_id: str = "default", emit=None) -> dict:
    ensure_dirs(project_id=project_id)
    sp = sources_path(project_id)
    source_path = sp / source_relative_path

    if not source_path.exists():
        await _emit_optional(emit, "error", source=source_relative_path, message="File not found")
        return {"source": source_relative_path, "status": "error", "error": "File not found"}

    content_hash = compute_source_hash(str(source_path))
    if not force:
        cached = get_ingest_cache(source_relative_path, project_id=project_id)
        if cached == content_hash:
            await _emit_optional(emit, "cached", source=source_relative_path, message="Already processed (cached)")
            return {"source": source_relative_path, "status": "cached",
                    "wiki_pages_created": [], "wiki_pages_updated": []}

    await _emit_optional(emit, "stage", source=source_relative_path,
                         stage="parse", message=f"正在解析文件: {source_relative_path}")
    try:
        wp = wiki_path(project_id)
        media_dir = str(wp / "media")
        content, _extracted_images, parse_method = await _parse_source_content(source_path, media_dir=media_dir)
    except Exception as e:
        await _emit_optional(emit, "error", source=source_relative_path, message=f"解析失败: {e}")
        return {"source": source_relative_path, "status": "error", "error": f"Parse error: {e}"}

    max_chars = 60000
    content = _strip_images(content)
    truncated = len(content) > max_chars
    if truncated:
        content = content[:max_chars] + "\n\n[Content truncated...]"
    await _emit_optional(emit, "stage_done", source=source_relative_path,
                         stage="parse",
                         message=f"解析完成: {len(content):,} 字符 ({parse_method})" + (" (已截断)" if truncated else ""))

    await _emit_optional(emit, "stage", source=source_relative_path,
                         stage="plan", message="Step 1/4: 调用大模型规划 A 组 5 类核心知识页面...")
    try:
        # Primary: LLM 规划 5 类 (source/concept/formula/principle/procedure)
        plan_llm = await _generate_core_plan_llm(
            content,
            source_title=source_relative_path,
            page_count=0,
            project_id=project_id,
            emit=emit,
            source_relative_path=source_relative_path,
        )
        if plan_llm and any(plan_llm.get(k) for k in ("concepts", "formulas", "principles", "procedures", "source")):
            core_plan = _llm_plan_to_core_plan(plan_llm, source_title=source_relative_path)
            await _emit_optional(emit, "info", source=source_relative_path,
                                 message="LLM 规划成功；回退启发式未启用。")
        else:
            await _emit_optional(emit, "info", source=source_relative_path,
                                 message="LLM 规划为空，回退到启发式。")
            core_plan = _fallback_analysis_from_text(content)
    except Exception as e:
        await _emit_optional(emit, "error", source=source_relative_path, message=f"知识规划失败: {e}")
        return {"source": source_relative_path, "status": "error", "error": f"Planning error: {e}"}

    counts = _knowledge_counts(core_plan)
    await _emit_optional(emit, "stage_done", source=source_relative_path,
                         stage="plan",
                         message=f"规划完成: {counts['concepts']} 个概念, {counts['formulas']} 个公式, {counts['principles']} 个原理"
                                 + (f", {len(core_plan.get('procedures', []))} 个方法" if core_plan.get('procedures') else ""),
                         details=_analysis_details(core_plan))

    await _emit_optional(emit, "stage", source=source_relative_path,
                         stage="generate_core",
                         message=f"Step 2/4: LLM 正在生成主干 Wiki 页面..."
                                 f"({counts['concepts']} 概念 + {counts['formulas']} 公式 + {counts['principles']} 原理)")
    try:
        core_pages = await _generate_core_pages(
            core_plan,
            project_id=project_id,
            source_relative_path=source_relative_path,
            emit=emit,
        )
        core_pages = [p for p in core_pages if p.get("page_type") in {"concept", "formula", "principle"}]
    except Exception as e:
        await _emit_optional(emit, "error", source=source_relative_path, message=f"主干页面生成失败: {e}")
        return {"source": source_relative_path, "status": "error", "error": f"Core generation error: {e}"}

    await _emit_optional(emit, "stage_done", source=source_relative_path,
                         stage="generate_core", message=f"主干页面生成完成: {len(core_pages)} 个页面")

    await _emit_optional(emit, "stage", source=source_relative_path,
                         stage="derive", message="Step 3/4: LLM 正在基于主干页面生成综合、问答和学习指引...")
    try:
        derived = await _generate_derived_analysis(
            core_plan,
            core_pages,
            emit=emit,
            source_relative_path=source_relative_path,
        )
        analysis = _merge_derived_analysis(core_plan, derived)
    except Exception as e:
        await _emit_optional(emit, "error", source=source_relative_path, message=f"进阶内容生成失败: {e}")
        return {"source": source_relative_path, "status": "error", "error": f"Derived generation error: {e}"}

    counts = _knowledge_counts(analysis)
    await _emit_optional(emit, "stage_done", source=source_relative_path,
                         stage="derive",
                         message=f"进阶内容生成完成: {counts['synthesis']} 个综合, "
                                 f"{counts['inquiry']} 个问答, {counts['guide']} 个学习指引",
                         details=_analysis_details(analysis))

    await _emit_optional(emit, "stage", source=source_relative_path,
                         stage="generate_derived", message="Step 4/4: 正在组装派生 Wiki 页面并校验补全...")
    try:
        pages = _ensure_pages_from_analysis(analysis, core_pages, source_relative_path)
    except Exception as e:
        await _emit_optional(emit, "error", source=source_relative_path, message=f"页面组装失败: {e}")
        return {"source": source_relative_path, "status": "error", "error": f"Page assembly error: {e}"}

    await _emit_optional(emit, "stage_done", source=source_relative_path,
                         stage="generate_derived", message=f"页面组装完成: {len(pages)} 个页面")

    await _emit_optional(emit, "stage", source=source_relative_path,
                         stage="verify_refs",
                         message="Step 3.5/4: 校验引用 [ref:…] 标号并反查原页 offset...")
    try:
        _verify_cite_refs(pages, project_id)
    except Exception as e:
        # 校验失败不阻塞写入 —— 标记到日志，UI 仍能渲染
        await _emit_optional(emit, "warn", source=source_relative_path,
                             message=f"引用校验失败 (不阻塞): {e}")

    await _emit_optional(emit, "stage_done", source=source_relative_path,
                         stage="verify_refs", message="引用校验完成")

    await _emit_optional(emit, "stage", source=source_relative_path,
                         stage="write", message=f"正在写入 {len(pages)} 个页面...", total=len(pages))
    created = []
    updated = []
    for i, page in enumerate(pages):
        existing = read_wiki_page(page["path"], project_id=project_id) if page.get("path") else None
        action = "更新" if existing else "新建"
        await _emit_optional(emit, "write_page", source=source_relative_path,
                             message=f"[{i + 1}/{len(pages)}] {action}: {page.get('title', page.get('path', '?'))} ({page.get('page_type', 'concept')})",
                             current=i + 1, total=len(pages),
                             title=page.get("title", page.get("path", "?")),
                             page_type=page.get("page_type", "concept"),
                             action=action)

    outputs = _write_ingest_outputs(pages, analysis, source_relative_path, project_id=project_id)
    created = outputs["created"]
    updated = outputs["updated"]
    await _emit_optional(emit, "stage_done", source=source_relative_path,
                         stage="write", message=f"写入完成: {len(created)} 新建, {len(updated)} 更新",
                         created=len(created), updated=len(updated), total=len(pages))

    set_ingest_cache(source_relative_path, content_hash, project_id=project_id)

    # Rebuild the learning graph so the v2/v3 endpoints (graph, insights,
    # learning path, mastery) reflect the freshly written wiki pages.
    # Failure here must not fail ingest — the user can still rebuild via
    # the ``?rebuild=true`` query param.
    try:
        from services.graph_engine import build_graph
        build_graph(project_id=project_id, force=True)
        await _emit_optional(emit, "graph_built", source=source_relative_path,
                             message="learning graph rebuilt from updated wiki")
    except Exception as e:
        await _emit_optional(emit, "graph_build_warning", source=source_relative_path,
                             message=f"graph rebuild skipped: {e}")

    await _emit_optional(emit, "complete", source=source_relative_path,
                         message=f"Done: {len(created)} pages created",
                         created=created, updated=updated)

    return {
        "source": source_relative_path,
        "status": "generated",
        "wiki_pages_created": created,
        "wiki_pages_updated": updated,
        "concepts_extracted": outputs["concepts"],
    }


async def run_ingest(source_relative_path: str, force: bool = False, *, project_id: str = "default") -> dict:
    """Run the multi-stage ingest pipeline for a single source file.

    Returns: {source, status, wiki_pages_created, wiki_pages_updated, concepts_extracted, error}
    """
    return await _run_ingest_pipeline(source_relative_path, force=force, project_id=project_id)


async def run_ingest_streaming(source_paths: list[str], force: bool = False, *, project_id: str = "default"):
    """Streaming version of run_ingest — yields progress events as SSE dicts."""
    for source_relative_path in source_paths:
        queue: asyncio.Queue = asyncio.Queue()

        async def collect(event: str, **kwargs):
            await queue.put({"event": event, **kwargs})

        async def run_one():
            try:
                await _run_ingest_pipeline(source_relative_path, force=force, project_id=project_id, emit=collect)
            finally:
                await queue.put(None)

        task = asyncio.create_task(run_one())
        while True:
            event = await queue.get()
            if event is None:
                break
            yield event
        await task


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

    await _run_ingest_pipeline(source_relative_path, force=force, project_id=project_id, emit=emit)


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
