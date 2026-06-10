"""API routes for wiki page CRUD."""

from fastapi import APIRouter, HTTPException, Query

from models.wiki import WikiPageCreate, WikiPageUpdate
from storage.wiki_store import (
    delete_wiki_page,
    ensure_dirs,
    list_wiki_pages,
    read_wiki_page,
    wiki_path,
    write_wiki_page,
)

router = APIRouter(prefix="/api/wiki", tags=["wiki"])


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
    path = f"{page.page_type}s/{slug}.md"

    full_path = write_wiki_page(
        relative_path=path,
        title=page.title,
        page_type=page.page_type,
        content=page.content,
        sources=page.sources,
        tags=page.tags,
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
