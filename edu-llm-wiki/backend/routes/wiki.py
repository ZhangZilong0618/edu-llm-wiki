"""API routes for wiki page CRUD."""

from fastapi import APIRouter, HTTPException, Query

from models.wiki import BStageRequest, CStageRequest, StageGenerateResult, WikiPageCreate, WikiPageUpdate
from storage.wiki_store import (
    delete_wiki_page,
    ensure_dirs,
    list_wiki_pages,
    read_wiki_page,
    wiki_path,
    write_wiki_page,
)

router = APIRouter(prefix="/api/wiki", tags=["wiki"])


_FOLDER_BY_TYPE = {
    "concept": "concepts",
    "formula": "formulas",
    "principle": "principles",
    "source": "sources",
    "synthesis": "synthesis",
    "inquiry": "inquiries",
    "guide": "guides",
}


@router.get("/pages")
async def get_pages(page_type: str | None = None, project_id: str = Query("default")):
    """List all wiki pages, optionally filtered by type."""
    return list_wiki_pages(page_type=page_type, project_id=project_id)


@router.get("/pages/{relative_path:path}")
async def get_page(relative_path: str, project_id: str = Query("default")):
    """Get a single wiki page by path."""
    page = read_wiki_page(relative_path, project_id=project_id)
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    return page


@router.post("/pages")
async def create_page(page: WikiPageCreate, project_id: str = Query("default")):
    """Create a new wiki page."""
    ensure_dirs(project_id=project_id)

    # Determine path from title and type
    import re
    slug = re.sub(r'[^\w一-鿿\s-]', '', page.title).strip().replace(' ', '_')
    folder = _FOLDER_BY_TYPE.get(page.page_type, f"{page.page_type}s")
    path = f"{folder}/{slug}.md"

    full_path = write_wiki_page(
        relative_path=path,
        title=page.title,
        page_type=page.page_type,
        content=page.content,
        sources=page.sources,
        tags=page.tags,
        prerequisites=page.prerequisites,
        difficulty=page.difficulty,
        related=page.related,
        common_misconceptions=page.common_misconceptions,
        worked_example_ref=page.worked_example_ref,
        last_reviewed=page.last_reviewed,
        project_id=project_id,
    )

    return {"path": path, "full_path": full_path, "title": page.title}


@router.put("/pages/{relative_path:path}")
async def update_page(relative_path: str, update: WikiPageUpdate, project_id: str = Query("default")):
    """Update an existing wiki page."""
    existing = read_wiki_page(relative_path, project_id=project_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Page not found")

    write_wiki_page(
        relative_path=relative_path,
        title=update.title or existing["title"],
        page_type=existing["page_type"],
        content=update.content if update.content is not None else existing["content"],
        sources=update.sources if update.sources is not None else existing["sources"],
        tags=update.tags if update.tags is not None else existing["tags"],
        prerequisites=update.prerequisites if update.prerequisites is not None else existing.get("prerequisites", []),
        difficulty=update.difficulty if update.difficulty is not None else existing.get("difficulty"),
        related=update.related if update.related is not None else existing.get("related", []),
        common_misconceptions=update.common_misconceptions if update.common_misconceptions is not None else existing.get("common_misconceptions", []),
        worked_example_ref=update.worked_example_ref if update.worked_example_ref is not None else existing.get("worked_example_ref", []),
        last_reviewed=update.last_reviewed if update.last_reviewed is not None else existing.get("last_reviewed", ""),
        project_id=project_id,
    )

    return {"path": relative_path, "status": "updated"}


@router.delete("/pages/{relative_path:path}")
async def delete_page(relative_path: str, project_id: str = Query("default")):
    """Delete a wiki page."""
    deleted = delete_wiki_page(relative_path, project_id=project_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Page not found")
    return {"path": relative_path, "status": "deleted"}


@router.get("/system/purpose")
async def get_purpose(project_id: str = Query("default")):
    """Get the purpose.md content."""
    p = wiki_path(project_id) / "purpose.md"
    if p.exists():
        return {"content": p.read_text(encoding="utf-8")}
    return {"content": ""}


@router.put("/system/purpose")
async def update_purpose(content: dict, project_id: str = Query("default")):
    """Update the purpose.md content."""
    p = wiki_path(project_id) / "purpose.md"
    p.write_text(content.get("content", ""), encoding="utf-8")
    return {"status": "updated"}


@router.get("/system/schema")
async def get_schema(project_id: str = Query("default")):
    """Get the schema.md content."""
    p = wiki_path(project_id) / "schema.md"
    if p.exists():
        return {"content": p.read_text(encoding="utf-8")}
    return {"content": ""}


@router.put("/system/schema")
async def update_schema(content: dict, project_id: str = Query("default")):
    """Update the schema.md content."""
    p = wiki_path(project_id) / "schema.md"
    p.write_text(content.get("content", ""), encoding="utf-8")
    return {"status": "updated"}


# ---------- B / C 阶段按需触发（独立 endpoint）----------

@router.post("/generate-b-stage", response_model=StageGenerateResult)
async def generate_b_stage(req: BStageRequest, project_id: str = Query("default")):
    """基于一个 A 组页面，按需生成 B 组（example / misconception）页面。

    用法：前端在 Concept / Formula / Principle 详情页的"..." 菜单里
    挂"基于此页生成 Example / 找出易错点"按钮。
    """
    from services.ingest_engine import _generate_b_stage_pages, _verify_cite_refs

    if not req.source_file or not req.page_types:
        raise HTTPException(status_code=400, detail="source_file and page_types are required")

    # 用 req.source_file 找出"被此 source 引用"的一个 anchor page
    all_pages = list_wiki_pages(project_id=project_id)
    candidate = next(
        (
            p for p in all_pages
            if req.source_file in (p.get("sources") or [])
        ),
        None,
    )
    if not candidate:
        raise HTTPException(
            status_code=404,
            detail=f"No A-stage page found that references source '{req.source_file}'",
        )
    full_anchor = read_wiki_page(candidate["path"], project_id=project_id) or candidate
    new_pages = await _generate_b_stage_pages(
        anchor_page=full_anchor,
        page_types=req.page_types,
        source_file=req.source_file,
        extra_context=req.extra_context,
        project_id=project_id,
    )
    if not new_pages:
        return StageGenerateResult(pages_created=[], pages_updated=[], error="LLM 未返回任何页面")

    _verify_cite_refs(new_pages, project_id)

    created: list[str] = []
    updated: list[str] = []
    for p in new_pages:
        try:
            path = p["path"]
            existing = read_wiki_page(path, project_id=project_id)
            write_wiki_page(
                relative_path=path,
                title=p.get("title", "Untitled"),
                page_type=p.get("page_type", "example"),
                content=p.get("content", ""),
                sources=p.get("sources", [req.source_file]),
                tags=p.get("tags", []),
                prerequisites=p.get("prerequisites", []),
                project_id=project_id,
            )
            (updated if existing else created).append(path)
        except Exception as exc:
            continue
    return StageGenerateResult(pages_created=created, pages_updated=updated, error="")


@router.post("/generate-c-stage", response_model=StageGenerateResult)
async def generate_c_stage(req: CStageRequest, project_id: str = Query("default")):
    """按需生成一个 C 组（synthesis / learning_path / learning_objective / rubric）页面。"""
    from services.ingest_engine import _generate_c_stage_page, _verify_cite_refs

    if req.page_type not in ("synthesis", "learning_path", "learning_objective", "rubric"):
        raise HTTPException(status_code=400, detail=f"Unsupported C-stage page_type: {req.page_type}")

    targets: list[dict] = []
    for p in req.target_pages or []:
        full = read_wiki_page(p, project_id=project_id)
        if full:
            targets.append(full)
    if not targets:
        # 兜底：用项目里所有 A 组页
        for meta in list_wiki_pages(project_id=project_id):
            full = read_wiki_page(meta["path"], project_id=project_id)
            if full and full.get("page_type") in ("concept", "formula", "principle", "procedure"):
                targets.append(full)

    source_files: list[str] = []
    for t in targets:
        for s in t.get("sources", []) or []:
            if s not in source_files:
                source_files.append(s)

    new_page = await _generate_c_stage_page(
        page_type=req.page_type,
        target_pages=targets,
        source_files=source_files,
        extra_context=req.extra_context,
        project_id=project_id,
    )
    if not new_page:
        return StageGenerateResult(pages_created=[], pages_updated=[], error="LLM 未返回任何内容")

    _verify_cite_refs([new_page], project_id)

    path = new_page.get("path")
    if not path:
        return StageGenerateResult(error="生成结果缺 path 字段")
    existing = read_wiki_page(path, project_id=project_id)
    write_wiki_page(
        relative_path=path,
        title=new_page.get("title", req.page_type.title()),
        page_type=new_page.get("page_type", req.page_type),
        content=new_page.get("content", ""),
        sources=new_page.get("sources", source_files),
        tags=new_page.get("tags", []),
        prerequisites=new_page.get("prerequisites", []),
        project_id=project_id,
    )
    return StageGenerateResult(
        pages_created=[] if existing else [path],
        pages_updated=[path] if existing else [],
        error="",
    )
