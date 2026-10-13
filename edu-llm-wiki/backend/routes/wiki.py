"""API routes for wiki page CRUD."""

from fastapi import APIRouter, Header, HTTPException, Query

from models.wiki import WikiPageCreate, WikiPageUpdate
from storage.wiki_store import (
    delete_wiki_page,
    ensure_dirs,
    is_private_learner_page_path,
    list_wiki_pages,
    read_wiki_page,
    wiki_path,
    write_wiki_page,
)

router = APIRouter(prefix="/api/wiki", tags=["wiki"])


def _require_admin_token(admin_token: str | None, x_admin_token: str | None) -> None:
    """Protect maintenance projections when the deployment has a token."""
    from config import settings

    expected = (getattr(settings, "api_token", "") or "").strip()
    if expected and (admin_token or x_admin_token or "").strip() != expected:
        raise HTTPException(status_code=401, detail="admin_token missing or invalid")


_FOLDER_BY_TYPE = {
    "concept": "concepts",
    "fact": "facts",
    "formula": "formulas",
    "principle": "principles",
}


@router.get("/pages")
async def get_pages(page_type: str | None = None, project_id: str = Query("default")):
    """List all wiki pages, optionally filtered by type."""
    return list_wiki_pages(page_type=page_type, project_id=project_id)


@router.get("/pages/{relative_path:path}")
async def get_page(relative_path: str, project_id: str = Query("default")):
    """Get a single wiki page by path.

    精确路径找不到时按标题/文件名回退:聊天与页面正文里的 [[标题]]
    wikilink 通常只有标题不带目录(页面实际在 concepts/ 等子目录),
    去掉 .md 后缀与 #锚点 后做全库匹配;多个同名页取路径最浅的。
    """
    if is_private_learner_page_path(relative_path):
        raise HTTPException(status_code=404, detail="Page not found")
    page = read_wiki_page(relative_path, project_id=project_id)
    if page and page.get("page_type") == "learner_profile":
        raise HTTPException(status_code=404, detail="Page not found")
    if not page:
        stem = relative_path.split("#", 1)[0].strip().removesuffix(".md")
        # 防御双重编码:调用方若把已编码串再编码一次,服务端收到的字面量
        # 仍是 %XX 形式;解码一次再匹配。
        if "%" in stem:
            try:
                from urllib.parse import unquote

                decoded = unquote(stem)
                if decoded != stem:
                    page = read_wiki_page(decoded, project_id=project_id)
                    if page:
                        return page
                    stem = decoded.split("#", 1)[0].strip().removesuffix(".md")
            except Exception:
                pass
        if stem:
            candidates = []
            for meta in list_wiki_pages(project_id=project_id):
                meta_title = str(meta.get("title") or "").strip()
                base = str(meta.get("path") or "").rsplit("/", 1)[-1].removesuffix(".md")
                if meta_title == stem or base == stem:
                    candidates.append(str(meta.get("path")))
            for cand_path in sorted(candidates, key=len):
                page = read_wiki_page(cand_path, project_id=project_id)
                if page and page.get("page_type") != "learner_profile":
                    break
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
    if is_private_learner_page_path(relative_path):
        raise HTTPException(status_code=404, detail="Page not found")
    existing = read_wiki_page(relative_path, project_id=project_id)
    if not existing or existing.get("page_type") == "learner_profile":
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
    if is_private_learner_page_path(relative_path):
        raise HTTPException(status_code=404, detail="Page not found")
    existing = read_wiki_page(relative_path, project_id=project_id)
    if existing and existing.get("page_type") == "learner_profile":
        raise HTTPException(status_code=404, detail="Page not found")
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


@router.post("/system/learning-projection/rebuild")
async def rebuild_learning_projection(
    project_id: str = Query("default"),
    include_failed: bool = Query(True),
    admin_token: str | None = Query(None),
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
):
    """Recreate generated learning Wiki pages from the SQLite event ledger."""
    _require_admin_token(admin_token, x_admin_token)
    from services.wiki_auto_update import rebuild_projection

    return rebuild_projection(project_id, include_failed=include_failed)


@router.post("/system/learning-projection/replay-failed")
async def replay_learning_projection(
    project_id: str = Query("default"),
    user_id: str | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    admin_token: str | None = Query(None),
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
):
    """Retry failed or abandoned Wiki projection events."""
    _require_admin_token(admin_token, x_admin_token)
    from services.wiki_auto_update import replay_failed_events

    return replay_failed_events(project_id, user_id=user_id, limit=limit)
