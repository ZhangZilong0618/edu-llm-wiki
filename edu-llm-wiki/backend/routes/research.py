"""Deep research actions for wiki pages."""

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query

from models.research import ResearchRequest, ResearchResponse, ResearchSaveRequest
from services.language import language_instruction
from services.llm_client import chat_complete
from storage.wiki_store import list_wiki_pages, read_wiki_page, write_wiki_page

router = APIRouter(prefix="/api/research", tags=["research"])


ACTION_LABELS = {
    "explain": "深入解释",
    "prerequisites": "补前置知识",
    "related": "关联知识",
    "practice": "生成练习",
    "completeness": "检查完整性",
    "derive": "推导公式",
    "variables": "变量与单位",
    "boundaries": "适用边界",
    "examples": "材料案例",
    "hint": "分步提示",
    "check_answer": "检查答案",
    "learning_path": "生成学习路线",
    "outline": "提炼大纲",
    "custom": "自定义研究",
}


PAGE_TYPE_GUIDANCE = {
    "concept": "关注本质定义、例子/反例、易混概念、材料科学语境和前置概念。",
    "formula": "关注变量和单位、推导脉络、适用条件、极限情况、常见误用和数值例题。",
    "principle": "关注物理图像、条件边界、失效情况、关联公式、实验现象和材料案例。",
    "source": "关注文档大纲、核心概念、公式/图表清单、学习路线和待补 wiki 页面。",
    "synthesis": "关注多来源证据、观点对比、冲突点、结论表格和可沉淀的新页面。",
    "inquiry": "关注多元视角的并列答案、未决问题和可继续追问的方向。",
    "guide": "关注学习顺序、复习策略、质量提醒和维护注意事项。",
}


ACTION_GUIDANCE = {
    "explain": "用更清楚的方式解释当前页。给出直觉解释、关键句和一个具体例子。",
    "prerequisites": "列出理解当前页前需要掌握的知识，并说明学习顺序。",
    "related": "找出当前页与相关 wiki 页面的关系，说明是前置、并列、应用、推导还是易混。",
    "practice": "围绕当前页生成 2-3 个练习，题型要多样，优先混合选择题、填空题、简答/计算题；每题包含题型、题目、提示和参考答案。选择题必须单独给出“选项”小节，并用 A./B./C./D. 选项；填空题用 ____ 或 （ ） 表示空。",
    "completeness": "检查当前页是否缺定义、公式、变量、例子、适用边界、来源或练习，并给出补全建议。",
    "derive": "如果当前页是公式，给出可教学的推导过程、假设条件和物理意义。",
    "variables": "如果当前页含公式，逐项解释变量、单位、量纲和可测量方式。",
    "boundaries": "说明适用范围、失效条件、近似假设和常见误用。",
    "examples": "给出材料科学中的真实或教学案例，说明当前知识点如何使用。",
    "hint": "如果当前页是习题，给出逐步提示，但先不要直接给最终答案。",
    "check_answer": "如果当前页是习题，给出判分标准、常见错误和标准解题路径。",
    "learning_path": "如果当前页是来源页，按章节和难度生成学习路线。",
    "outline": "如果当前页是来源页，提炼结构化大纲、关键概念、公式和练习入口。",
    "custom": "严格围绕用户补充要求展开研究；如果用户要求不清晰，先按当前页面内容补全一个可教学、可保存的研究笔记。",
}


def _related_pages(page: dict, *, project_id: str) -> list[dict]:
    """Find a small set of related pages from source overlap and wikilinks."""
    pages = list_wiki_pages(project_id=project_id)
    source_set = set(page.get("sources", []) or [])
    content = page.get("content", "")
    related = []
    for candidate in pages:
        if candidate["path"] == page["path"]:
            continue
        score = 0
        candidate_page = read_wiki_page(candidate["path"], project_id=project_id)
        if not candidate_page:
            continue
        candidate_sources = set(candidate_page.get("sources", []) or [])
        if source_set and source_set & candidate_sources:
            score += 3
        path_id = candidate["path"].replace(".md", "")
        if f"[[{path_id}" in content or candidate["title"] in content:
            score += 4
        if page.get("title") and page["title"] in candidate.get("summary", ""):
            score += 2
        if score:
            related.append({**candidate, "score": score})
    related.sort(key=lambda p: (-p["score"], p["title"]))
    return related[:8]


def _research_title(page: dict, action: str) -> str:
    label = ACTION_LABELS.get(action, action)
    return f"{label}: {page.get('title', page.get('path', '当前页'))}"


@router.post("/run", response_model=ResearchResponse)
async def run_research(req: ResearchRequest, project_id: str = Query("default")):
    page = read_wiki_page(req.page_path, project_id=project_id)
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")

    action_label = ACTION_LABELS.get(req.action, req.action)
    related = _related_pages(page, project_id=project_id)
    related_context = "\n".join(
        f"- {p['title']} ({p['type']}): {p['path']} — {p.get('summary', '')[:160]}"
        for p in related
    ) or "无"
    type_guidance = PAGE_TYPE_GUIDANCE.get(page.get("page_type", ""), "根据页面内容选择合适的教学分析方式。")
    action_guidance = ACTION_GUIDANCE.get(req.action, "围绕当前页做深入研究，保持教学性和可沉淀性。")

    prompt = f"""你是 Edu-LLM-Wiki 的深入探究助手。你的任务不是普通聊天，而是帮助用户把当前 wiki 页面发展成更好的学习/研究节点。

当前动作：{action_label}
动作要求：{action_guidance}
页面类型要求：{type_guidance}

输出要求：
- {language_instruction()}
- 所有数学公式必须使用 LaTeX：行内 $...$（如 $\\sigma$、$\\varepsilon$），块级 $$...$$。不要写裸 LaTeX 命令。
- 内容要具体、可教学、能回流到 wiki。
- 不要编造不存在的来源；如果是不确定推断，要明确说明。
- 根据动作组织 3-5 个短小清晰的小节。
- 如引用相关页面，请使用 [[path/to/page]] 形式。
- 不要输出闲聊式开场。
"""

    user = f"""当前页面：
路径：{page['path']}
标题：{page['title']}
类型：{page['page_type']}
来源：{', '.join(page.get('sources', []) or []) or '无'}

页面内容：
{page.get('content', '')[:24000]}

相关页面候选：
{related_context}

用户补充要求：
{req.note or '无'}
"""

    content = await chat_complete(
        system_prompt=prompt,
        messages=[{"role": "user", "content": user}],
        temperature=0.35,
        max_tokens=4096,
    )
    title = _research_title(page, req.action)
    return ResearchResponse(action=req.action, title=title, content=content.strip(), related_pages=related)


@router.post("/save-note")
async def save_research_note(req: ResearchSaveRequest, project_id: str = Query("default")):
    page = read_wiki_page(req.page_path, project_id=project_id)
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")

    note = (
        "\n\n## 深入探究\n\n"
        f"### {req.title}\n\n"
        f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
        f"{req.content.strip()}\n"
    )
    content = (page.get("content") or "").rstrip() + note
    write_wiki_page(
        relative_path=page["path"],
        title=page["title"],
        page_type=page["page_type"],
        content=content,
        sources=page.get("sources", []),
        tags=page.get("tags", []),
        project_id=project_id,
    )
    updated = read_wiki_page(page["path"], project_id=project_id)
    return {"status": "saved", "page": updated}
