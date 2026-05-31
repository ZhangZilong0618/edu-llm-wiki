"""API routes for document ingestion."""

from fastapi import APIRouter, HTTPException, UploadFile, File, Query
from models.wiki import IngestRequest, IngestResult
from services.ingest_engine import run_ingest
from services.file_parser import parse_file
from storage.wiki_store import sources_path, ensure_dirs
import aiofiles
import os

router = APIRouter(prefix="/api/ingest", tags=["ingest"])


@router.post("/upload")
async def upload_file(file: UploadFile = File(...), project_id: str = Query("default")):
    """Upload a document to sources/ directory."""
    ensure_dirs(project_id=project_id)
    sp = sources_path(project_id)

    # Sanitize filename
    safe_name = file.filename.replace("..", "").replace("/", "_").replace("\\", "_")
    dest = sp / safe_name

    async with aiofiles.open(dest, "wb") as f:
        content = await file.read()
        await f.write(content)

    return {"filename": safe_name, "size": len(content)}


@router.post("/run", response_model=IngestResult)
async def run_ingest_endpoint(req: IngestRequest, project_id: str = Query("default")):
    """Run the two-step ingest pipeline on source files."""
    results = []
    for source_path in req.source_paths:
        result = await run_ingest(source_path, force=req.force, project_id=project_id)
        results.append(result)
    return results[0] if len(results) == 1 else results


@router.get("/sources")
async def list_sources(project_id: str = Query("default")):
    """List all files in sources/ directory."""
    sp = sources_path(project_id)
    if not sp.exists():
        return []
    files = []
    for f in sorted(sp.iterdir()):
        if f.is_file():
            files.append({
                "name": f.name,
                "size": f.stat().st_size,
                "modified": f.stat().st_mtime,
            })
    return files


@router.delete("/sources/{filename}")
async def delete_source(filename: str, project_id: str = Query("default")):
    """Delete a source file and cascade-clean wiki pages."""
    sp = sources_path(project_id)
    file_path = sp / filename
    if file_path.exists():
        file_path.unlink()
        return {"status": "deleted"}
    raise HTTPException(status_code=404, detail="File not found")


@router.post("/import-folder")
async def import_folder(folder_path: str, project_id: str = Query("default")):
    """Import all supported files from a folder recursively."""
    import glob
    supported = {".pdf", ".docx", ".pptx", ".xlsx", ".xls", ".md", ".txt"}
    imported = []
    folder = os.path.abspath(folder_path)
    if not os.path.isdir(folder):
        raise HTTPException(status_code=400, detail="Invalid folder path")

    for root, dirs, files in os.walk(folder):
        for fname in files:
            ext = os.path.splitext(fname)[1].lower()
            if ext in supported:
                src_path = os.path.join(root, fname)
                rel = os.path.relpath(src_path, folder)
                # Copy to sources
                dest = sources_path(project_id) / rel.replace("/", "_").replace("\\", "_")
                dest.parent.mkdir(parents=True, exist_ok=True)
                with open(src_path, "rb") as sf, open(dest, "wb") as df:
                    df.write(sf.read())
                imported.append({"name": fname, "relative": rel})

    return {"imported": len(imported), "files": imported}
