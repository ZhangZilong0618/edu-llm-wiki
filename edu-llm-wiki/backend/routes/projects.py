"""API routes for project management."""

from fastapi import APIRouter, HTTPException

from storage.wiki_store import create_project, delete_project, list_projects

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("")
async def get_projects():
    """List all projects."""
    return list_projects()


@router.post("")
async def create_project_endpoint(data: dict):
    """Create a new project with full wiki directory structure."""
    name = (data.get("name", "") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Project name required")
    try:
        return create_project(name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.delete("/{name}")
async def delete_project_endpoint(name: str):
    """Delete a project and all its data."""
    try:
        deleted = delete_project(name)
        if not deleted:
            raise HTTPException(status_code=404, detail="Project not found")
        return {"status": "deleted"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
