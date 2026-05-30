"""API routes for wiki page CRUD and lint."""

from fastapi import APIRouter, HTTPException
from models.wiki import WikiPage, WikiPageCreate, WikiPageUpdate
from storage.wiki_store import (
    list_wiki_pages, read_wiki_page, write_wiki_page, delete_wiki_page, update_index, ensure_dirs
)

router = APIRouter(prefix="/api/wiki", tags=["wiki"])


@router.get("/pages")
async def get_pages(page_type: str | None = None):
    """List all wiki pages, optionally filtered by type."""
    return list_wiki_pages(page_type=page_type)


@router.get("/pages/{relative_path:path}")
async def get_page(relative_path: str):
    """Get a single wiki page by path."""
    page = read_wiki_page(relative_path)
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    return page


@router.post("/pages")
async def create_page(page: WikiPageCreate):
    """Create a new wiki page."""
    ensure_dirs()

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
    )

    return {"path": path, "full_path": full_path, "title": page.title}


@router.put("/pages/{relative_path:path}")
async def update_page(relative_path: str, update: WikiPageUpdate):
    """Update an existing wiki page."""
    existing = read_wiki_page(relative_path)
    if not existing:
        raise HTTPException(status_code=404, detail="Page not found")

    full_path = write_wiki_page(
        relative_path=relative_path,
        title=update.title or existing["title"],
        page_type=existing["page_type"],
        content=update.content if update.content is not None else existing["content"],
        sources=update.sources if update.sources is not None else existing["sources"],
        tags=update.tags if update.tags is not None else existing["tags"],
    )

    return {"path": relative_path, "status": "updated"}


@router.delete("/pages/{relative_path:path}")
async def delete_page(relative_path: str):
    """Delete a wiki page."""
    deleted = delete_wiki_page(relative_path)
    if not deleted:
        raise HTTPException(status_code=404, detail="Page not found")
    return {"path": relative_path, "status": "deleted"}


@router.get("/system/purpose")
async def get_purpose():
    """Get the purpose.md content."""
    from storage.wiki_store import wiki_path
    p = wiki_path() / "purpose.md"
    if p.exists():
        return {"content": p.read_text(encoding="utf-8")}
    return {"content": ""}


@router.put("/system/purpose")
async def update_purpose(content: dict):
    """Update the purpose.md content."""
    from storage.wiki_store import wiki_path
    p = wiki_path() / "purpose.md"
    p.write_text(content.get("content", ""), encoding="utf-8")
    return {"status": "updated"}


@router.get("/system/schema")
async def get_schema():
    """Get the schema.md content."""
    from storage.wiki_store import wiki_path
    p = wiki_path() / "schema.md"
    if p.exists():
        return {"content": p.read_text(encoding="utf-8")}
    return {"content": ""}


@router.put("/system/schema")
async def update_schema(content: dict):
    """Update the schema.md content."""
    from storage.wiki_store import wiki_path
    p = wiki_path() / "schema.md"
    p.write_text(content.get("content", ""), encoding="utf-8")
    return {"status": "updated"}
