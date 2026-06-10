"""Exercise-specific learning APIs."""

import json
import re

from fastapi import APIRouter, HTTPException, Query

from models.exercise import ExerciseCheckRequest, ExerciseCheckResponse, ExerciseCompleteSolutionRequest, ExerciseCompleteSolutionResponse
from services.language import language_instruction
from services.llm_client import chat_complete
from storage.wiki_store import list_wiki_pages, read_wiki_page, write_wiki_page

router = APIRouter(prefix="/api/exercises", tags=["exercises"])


SYSTEM_PROMPT = """你是 Edu-LLM-Wiki 的练习判题助手。你的任务是判断学生答案，而不是普通聊天。

请依据题目、参考解答和当前 wiki 页面内容，给出结构化反馈。

判题要求：
- 如果学生只是说“不会/不太会/不知道/没思路”，level 必须是 weak，明确说明还不能判分。
- 不要因为答案短就直接判错；只要核心原理、公式或推理方向正确，可以给 partial 或 good。
- 优先检查：使用的原理、关键公式、变量含义、推导关系、最终表达式、单位/条件。
- 如果参考解答是“待补充/请结合文档...”一类占位内容，请根据题目和上下文自行判断，并给出 suggested_answer。
- matched 和 missing 要写学生能看懂的中文/符号短语，不要写 LaTeX 命令内部词如 frac、left、right。
- suggested_answer 中如有数学公式，必须使用 LaTeX：行内 $...$（如 $\\sigma$、$\\varepsilon$），块级 $$...$$。不要写裸 LaTeX 命令。
- detail 用中文，具体指出下一步怎么改。

只返回 JSON，不要 markdown，不要额外解释。JSON schema:
{
  "level": "empty|weak|partial|good",
  "title": "短标题",
  "detail": "具体反馈",
  "matched": ["已覆盖要点"],
  "missing": ["建议补充要点"],
  "suggested_answer": "可选。标准解法或关键公式"
}
"""

COMPLETE_SOLUTION_PROMPT = """你是 Edu-LLM-Wiki 的习题解析生成助手。你的任务是给当前 exercise 页面补全或重新生成标准解答。

要求：
- 只输出“解答”正文，不要输出 frontmatter，不要重复题目标题。
- 如果当前解答区已有内容但质量差、占位、过短或用户要求重新生成，请直接重写一版更好的解析，不要受旧解析限制。
- 用中文。
- 如果是计算题，必须写出已知量、使用的原理/公式、推导步骤、最终表达式；必要时解释变量含义。
- 如果是概念题，必须给出清晰答案、判断依据、常见误区。
- 使用 Markdown 和 LaTeX：行内 $...$（如 $\\sigma$、$\\varepsilon$），块级 $$...$$。不要写裸 LaTeX 命令。
- 不要写“请结合文档”“待补充”“需要查阅原文”这类占位话。
- 如果上下文不足，也要基于题目和相关页面给出最合理的教学解法，并标明关键假设。
"""

REWRITE_EXERCISE_PROMPT = """你是 Edu-LLM-Wiki 的习题修复助手。你的任务是修复 exercise 页面结构。

当前题目可能存在：选择题缺少 A/B/C/D 选项、题型标错、答案带选项字母但题面无选项、解析不完整。

要求：
- 返回 JSON，不要 markdown fence，不要解释。
- type 只能是 multiple_choice、fill_blank、short_answer。
- 如果 type 是 multiple_choice，choices 必须包含 3-5 个可见选项，格式为 A. ... / B. ... / C. ... / D. ...。
- 如果无法合理补全选项，不要用 multiple_choice，改成 fill_blank 或 short_answer。
- 如果 question 使用 （ ） 或 ____，且答案不是选项集合，则优先用 fill_blank，并清除答案开头残留的 A./B./C./D.。
- solution 要能直接作为标准解析，说明正确答案和理由。解析中的数学公式必须使用 LaTeX：行内 $...$（如 $\\sigma$、$\\varepsilon$），块级 $$...$$。不要写裸 LaTeX 命令。
- 内容必须基于题目、当前解析和同源 wiki 上下文，不要编造与材料无关的选项。

JSON schema:
{
  "type": "multiple_choice|fill_blank|short_answer",
  "question": "题干本身，不要混入 A./B./C./D. 选项。",
  "choices": ["A. 选项", "B. 选项", "C. 选项", "D. 选项"],
  "solution": "标准解析正文"
}
"""

PLACEHOLDER_RE = re.compile(r"(请结合文档|待补充|暂无|todo|见原始文档|结合文档中的定义)", re.IGNORECASE)


def _with_language(prompt: str) -> str:
    return f"{prompt.rstrip()}\n\n{language_instruction()}"


def _extract_json(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", cleaned)
        if not match:
            raise
        return json.loads(match.group(0))


def _trim(text: str | None, limit: int) -> str:
    if not text:
        return ""
    return text.strip()[:limit]


def _section(content: str, names: tuple[str, ...]) -> str:
    names_pattern = "|".join(re.escape(name) for name in names)
    match = re.search(rf"##\s*(?:{names_pattern})\s*\n([\s\S]*?)(?=\n##\s+|\Z)", content, re.IGNORECASE)
    return match.group(1).strip() if match else ""


def _has_useful_solution(content: str) -> bool:
    solution = _section(content, ("解答", "答案", "Answer", "Solution"))
    return bool(solution and len(solution.strip()) >= 12 and not PLACEHOLDER_RE.search(solution))


def _replace_solution_section(content: str, solution: str) -> str:
    clean_solution = solution.strip()
    if not clean_solution.startswith("##"):
        clean_solution = f"## 解答\n\n{clean_solution}"

    pattern = re.compile(r"##\s*(?:解答|答案|Answer|Solution)\s*\n[\s\S]*?(?=\n##\s+|\Z)", re.IGNORECASE)
    if pattern.search(content):
        return pattern.sub(lambda _match: clean_solution.rstrip(), content, count=1).rstrip() + "\n"

    question_match = re.search(r"(##\s*题目\s*\n[\s\S]*?)(?=\n##\s+|\Z)", content)
    if question_match:
        insert_at = question_match.end()
        return (content[:insert_at].rstrip() + "\n\n" + clean_solution + "\n\n" + content[insert_at:].lstrip()).rstrip() + "\n"
    return content.rstrip() + "\n\n" + clean_solution + "\n"


def _replace_exercise_sections(content: str, exercise_type: str, question: str, solution: str, choices: list[str] | None = None) -> str:
    clean_type = exercise_type.strip() or "short_answer"
    clean_question = question.strip()
    clean_solution = solution.strip()
    clean_choices = [choice.strip() for choice in (choices or []) if choice.strip()]

    updated = content
    type_block = f"## 题型\n\n{clean_type}"
    question_block = f"## 题目\n\n{clean_question}"
    options_block = "## 选项\n\n" + "\n".join(clean_choices) if clean_type == "multiple_choice" and clean_choices else ""
    solution_block = f"## 解答\n\n{clean_solution}"

    if re.search(r"##\s*(?:题型|Type)\s*\n[\s\S]*?(?=\n##\s+|\Z)", updated, re.IGNORECASE):
        updated = re.sub(r"##\s*(?:题型|Type)\s*\n[\s\S]*?(?=\n##\s+|\Z)", type_block, updated, count=1, flags=re.IGNORECASE)
    else:
        first_heading = re.search(r"##\s+", updated)
        insert_at = first_heading.start() if first_heading else len(updated)
        updated = updated[:insert_at].rstrip() + "\n\n" + type_block + "\n\n" + updated[insert_at:].lstrip()

    if re.search(r"##\s*(?:题目|Question|Problem)\s*\n[\s\S]*?(?=\n##\s+|\Z)", updated, re.IGNORECASE):
        updated = re.sub(r"##\s*(?:题目|Question|Problem)\s*\n[\s\S]*?(?=\n##\s+|\Z)", question_block, updated, count=1, flags=re.IGNORECASE)
    else:
        updated = updated.rstrip() + "\n\n" + question_block

    if re.search(r"##\s*(?:选项|Options|Choices)\s*\n[\s\S]*?(?=\n##\s+|\Z)", updated, re.IGNORECASE):
        replacement = options_block if options_block else ""
        updated = re.sub(r"\n?##\s*(?:选项|Options|Choices)\s*\n[\s\S]*?(?=\n##\s+|\Z)", ("\n" + replacement) if replacement else "", updated, count=1, flags=re.IGNORECASE)
    elif options_block:
        question_match = re.search(r"##\s*(?:题目|Question|Problem)\s*\n[\s\S]*?(?=\n##\s+|\Z)", updated, re.IGNORECASE)
        insert_at = question_match.end() if question_match else len(updated)
        updated = updated[:insert_at].rstrip() + "\n\n" + options_block + "\n\n" + updated[insert_at:].lstrip()

    if re.search(r"##\s*(?:解答|答案|Answer|Solution)\s*\n[\s\S]*?(?=\n##\s+|\Z)", updated, re.IGNORECASE):
        updated = re.sub(r"##\s*(?:解答|答案|Answer|Solution)\s*\n[\s\S]*?(?=\n##\s+|\Z)", solution_block, updated, count=1, flags=re.IGNORECASE)
    else:
        updated = updated.rstrip() + "\n\n" + solution_block
    return updated.rstrip() + "\n"


def _has_choice_options(question: str) -> bool:
    return bool(re.search(r"^\s*(?:[-*]\s*)?[A-Da-d][\.\)、:：]\s+", question, re.MULTILINE))


def _choice_list_valid(choices: list[str]) -> bool:
    return len(choices) >= 2 and all(re.match(r"^\s*[A-Ha-h][\.\)、:：]\s+", choice) for choice in choices[:2])


def _answer_starts_with_choice(solution: str) -> bool:
    return bool(re.match(r"^\s*(?:答案[:：]?\s*)?[A-Ha-h][\.\)、:：\s]", solution.strip()))


def _related_context(page: dict, *, project_id: str) -> str:
    sources = set(page.get("sources", []) or [])
    current_path = page.get("path", "")
    chunks: list[str] = []
    for summary in list_wiki_pages(project_id=project_id):
        if summary["path"] == current_path:
            continue
        if len(chunks) >= 8:
            break
        related = read_wiki_page(summary["path"], project_id=project_id)
        if not related:
            continue
        if sources and not (sources & set(related.get("sources", []) or [])):
            continue
        if related.get("page_type") not in {"formula", "principle", "concept", "source"}:
            continue
        chunks.append(f"### {related['title']} ({related['page_type']})\n{_trim(related.get('content', ''), 1200)}")
    return "\n\n".join(chunks)


@router.post("/check", response_model=ExerciseCheckResponse)
async def check_exercise(
    req: ExerciseCheckRequest,
    project_id: str = Query("default"),
) -> ExerciseCheckResponse:
    page_context = req.context or ""
    if not page_context and req.page_path:
        page = read_wiki_page(req.page_path, project_id=project_id)
        if page:
            page_context = page.get("content", "")

    user_prompt = f"""请判这道练习。

页面标题：{req.page_title or ""}
页面路径：{req.page_path or ""}

题目：
{_trim(req.question, 2500)}

学生答案：
{_trim(req.student_answer, 1500)}

参考解答：
{_trim(req.reference_answer, 2500) or "无或占位"}

当前页面上下文：
{_trim(page_context, 4000)}
"""

    raw = await chat_complete(
        system_prompt=_with_language(SYSTEM_PROMPT),
        messages=[{"role": "user", "content": user_prompt}],
        max_tokens=900,
        temperature=0.1,
        response_format={"type": "json_object"},
    )
    data = _extract_json(raw)
    level = data.get("level") if data.get("level") in {"empty", "weak", "partial", "good"} else "partial"
    return ExerciseCheckResponse(
        level=level,
        title=str(data.get("title") or "AI 判题反馈"),
        detail=str(data.get("detail") or "已完成判题，请对照建议修改答案。"),
        matched=[str(x) for x in data.get("matched", []) if str(x).strip()][:8],
        missing=[str(x) for x in data.get("missing", []) if str(x).strip()][:8],
        suggested_answer=str(data.get("suggested_answer") or "") or None,
        source="ai",
    )


@router.post("/complete-solution", response_model=ExerciseCompleteSolutionResponse)
async def complete_solution(
    req: ExerciseCompleteSolutionRequest,
    project_id: str = Query("default"),
) -> ExerciseCompleteSolutionResponse:
    page = read_wiki_page(req.page_path, project_id=project_id)
    if not page:
        raise HTTPException(status_code=404, detail="Exercise page not found")
    if page.get("page_type") != "exercise":
        raise HTTPException(status_code=400, detail="Page is not an exercise")

    content = page.get("content", "")
    question = _section(content, ("题目", "Question")) or content[:1500]
    choices_text = _section(content, ("选项", "Options", "Choices"))
    existing_solution = _section(content, ("解答", "答案", "Answer", "Solution"))
    exercise_type = _section(content, ("题型", "Type"))
    related_context = _related_context(page, project_id=project_id)
    should_rewrite_exercise = (
        "补全题面" in (req.note or "")
        or "补全选项" in (req.note or "")
        or (_answer_starts_with_choice(existing_solution) and not (_has_choice_options(question) or choices_text))
    )

    user_prompt = f"""请补全这个习题的标准解答。

页面标题：{page.get("title", "")}
页面路径：{req.page_path}
来源：{", ".join(page.get("sources", []) or [])}

当前题型：
{_trim(exercise_type, 200) or "未知"}

题目：
{_trim(question, 2500)}

选项：
{_trim(choices_text, 1200) or "无"}

当前解答区：
{_trim(existing_solution, 1200) or "无"}

用户补充要求：
{_trim(req.note, 800) or "无"}

同源相关 wiki 页面：
{_trim(related_context, 8000) or "无"}
"""
    try:
        if should_rewrite_exercise:
            raw = await chat_complete(
                system_prompt=_with_language(REWRITE_EXERCISE_PROMPT),
                messages=[{"role": "user", "content": user_prompt}],
                max_tokens=1800,
                temperature=0.2,
                response_format={"type": "json_object"},
            )
            data = _extract_json(raw)
            rewritten_type = str(data.get("type") or "short_answer").strip()
            rewritten_question = str(data.get("question") or question).strip()
            rewritten_choices = [str(choice).strip() for choice in data.get("choices", []) if str(choice).strip()] if isinstance(data.get("choices"), list) else []
            solution = str(data.get("solution") or "").strip()
            if rewritten_type == "multiple_choice" and not (_choice_list_valid(rewritten_choices) or _has_choice_options(rewritten_question)):
                rewritten_type = "short_answer"
            if rewritten_type == "multiple_choice" and not rewritten_choices and _has_choice_options(rewritten_question):
                lines = rewritten_question.splitlines()
                rewritten_choices = [line.strip() for line in lines if re.match(r"^\s*(?:[-*]\s*)?[A-Da-d][\.\)、:：]\s+", line)]
                rewritten_question = "\n".join(line for line in lines if not re.match(r"^\s*(?:[-*]\s*)?[A-Da-d][\.\)、:：]\s+", line)).strip()
            if rewritten_type == "fill_blank" and _answer_starts_with_choice(solution):
                solution = re.sub(r"^\s*(?:答案[:：]?\s*)?[A-Ha-h][\.\)、:：\s]*", "", solution).strip()
            updated_content = _replace_exercise_sections(content, rewritten_type, rewritten_question, solution, rewritten_choices)
        else:
            solution = await chat_complete(
                system_prompt=_with_language(COMPLETE_SOLUTION_PROMPT),
                messages=[{"role": "user", "content": user_prompt}],
                max_tokens=1500,
                temperature=0.2,
            )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI solution generation failed: {str(e)[:200]}") from e
    solution = re.sub(r"^```(?:markdown|md)?\s*|\s*```$", "", solution.strip())
    solution = re.sub(r"^(?:#+\s*)?解答\s*\n+", "", solution, flags=re.IGNORECASE).strip()
    solution = re.sub(r"^\*\*解答\*\*\s*\n+", "", solution, flags=re.IGNORECASE).strip()
    if not solution or PLACEHOLDER_RE.search(solution):
        raise HTTPException(status_code=502, detail="AI did not produce a usable solution")

    if not should_rewrite_exercise:
        updated_content = _replace_solution_section(content, solution)
    write_wiki_page(
        relative_path=req.page_path,
        title=page["title"],
        page_type=page["page_type"],
        content=updated_content,
        sources=page.get("sources", []),
        tags=page.get("tags", []),
        project_id=project_id,
    )
    updated_page = read_wiki_page(req.page_path, project_id=project_id)
    return ExerciseCompleteSolutionResponse(status="updated", solution=solution, page=updated_page or page)
