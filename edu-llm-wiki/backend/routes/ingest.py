"""API routes for document ingestion."""

import json
import mimetypes
import os
from pathlib import Path

import aiofiles
from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from models.wiki import IngestRequest, IngestResult
from services.ingest_engine import run_ingest, run_ingest_batch_streaming, run_ingest_streaming
from storage.wiki_store import ensure_dirs, sources_path

router = APIRouter(prefix="/api/ingest", tags=["ingest"])


SUPPORTED_UPLOAD_EXTENSIONS = {".pdf", ".docx", ".pptx", ".xlsx", ".xls", ".md", ".txt", ".markdown", ".rst"}


@router.post("/upload")
async def upload_file(file: UploadFile = File(...), project_id: str = Query("default")):
    """Upload a document to sources/ directory."""
    ensure_dirs(project_id=project_id)
    sp = sources_path(project_id)

    safe_name = file.filename.replace("..", "").replace("/", "_").replace("\\", "_")
    ext = Path(safe_name).suffix.lower()
    if ext not in SUPPORTED_UPLOAD_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Supported: {', '.join(sorted(SUPPORTED_UPLOAD_EXTENSIONS))}",
        )

    dest = sp / safe_name

    async with aiofiles.open(dest, "wb") as f:
        content = await file.read()
        await f.write(content)

    return {"filename": safe_name, "size": len(content)}


@router.post("/run-stream")
async def run_ingest_stream(req: IngestRequest, project_id: str = Query("default")):
    """Run ingest with SSE streaming for progress updates."""
    async def event_stream():
        async for event in run_ingest_streaming(req.source_paths, force=req.force, project_id=project_id):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/run-batch")
async def run_batch_stream(
    req: IngestRequest,
    concurrency: int = Query(3, ge=1, le=10),
    project_id: str = Query("default"),
):
    """Run concurrent batch ingest with SSE streaming.

    Processes multiple files in parallel (default 3 concurrent).
    Each event includes a 'source' field to identify which file it belongs to.
    """
    async def event_stream():
        async for event in run_ingest_batch_streaming(
            req.source_paths, force=req.force, concurrency=concurrency, project_id=project_id
        ):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
    return StreamingResponse(event_stream(), media_type="text/event-stream")


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
    supported = {".pdf", ".docx", ".pptx", ".xlsx", ".xls", ".md", ".txt"}
    imported = []
    folder = os.path.abspath(folder_path)
    if not os.path.isdir(folder):
        raise HTTPException(status_code=400, detail="Invalid folder path")

    for root, _dirs, files in os.walk(folder):
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


VIEWABLE_EXTENSIONS = {".pdf", ".pptx", ".docx", ".xlsx", ".txt", ".md"}

PARSEABLE_EXTENSIONS = {".pdf", ".docx", ".pptx", ".xlsx", ".xls", ".txt", ".md", ".markdown", ".rst"}


def _content_disposition(filename: str, disposition: str = "inline") -> str:
    """Build Content-Disposition header with RFC 5987 encoding for non-ASCII filenames."""
    try:
        filename.encode("latin-1")
        return f'{disposition}; filename="{filename}"'
    except UnicodeEncodeError:
        from urllib.parse import quote
        encoded = quote(filename)
        return f"{disposition}; filename*=UTF-8''{encoded}"


@router.get("/sources/{filename}/view")
async def view_source(filename: str, project_id: str = Query("default")):
    """Serve a source file for inline viewing in the browser."""
    sp = sources_path(project_id)
    file_path = sp / filename
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    ext = file_path.suffix.lower()
    if ext not in VIEWABLE_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"File type {ext} is not viewable")

    mime_type, _ = mimetypes.guess_type(str(file_path))
    if not mime_type:
        mime_type = "application/octet-stream"

    return FileResponse(
        path=str(file_path),
        media_type=mime_type,
        headers={"Content-Disposition": _content_disposition(filename)},
    )


@router.get("/sources/{filename}/parsed")
async def parse_source(filename: str, project_id: str = Query("default")):
    """Parse a source file and return extracted text + images for in-app preview."""
    from services.file_parser import parse_file
    from storage.wiki_store import wiki_path

    sp = sources_path(project_id)
    file_path = sp / filename
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    ext = file_path.suffix.lower()
    if ext not in {".pdf", ".docx", ".pptx", ".xlsx", ".txt", ".md", ".markdown", ".rst"}:
        raise HTTPException(status_code=400, detail=f"File type {ext} is not parseable")

    wp = wiki_path(project_id)
    media_dir = str(wp / "media")
    try:
        content, images = await parse_file(str(file_path), media_dir=media_dir)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Parse error: {e}") from e

    import re
    content = re.sub(r'!\[[^\]]*\]\([^)]+\)', '', content)
    content = re.sub(r'<img[^>]*/?>', '', content)
    content = re.sub(r'\n{3,}', '\n\n', content)

    image_urls = [f"/api/ingest/media/{img['filename']}?project_id={project_id}" for img in images]

    ext = file_path.suffix.lower()
    view_url = f"/api/ingest/sources/{filename}/view?project_id={project_id}" if ext in {".pdf"} else None

    return {
        "filename": filename,
        "content": content[:50000],
        "images": image_urls,
        "extension": ext,
        "view_url": view_url,
    }


@router.get("/media/{filename}")
async def serve_media(filename: str, project_id: str = Query("default")):
    """Serve an image file from the wiki media directory."""
    from storage.wiki_store import wiki_path

    # Sanitize path traversal
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    wp = wiki_path(project_id)
    media_path = wp / "media" / filename
    if not media_path.exists() or not media_path.is_file():
        raise HTTPException(status_code=404, detail="Media file not found")

    mime_type, _ = mimetypes.guess_type(str(media_path))
    if not mime_type:
        mime_type = "application/octet-stream"

    return FileResponse(
        path=str(media_path),
        media_type=mime_type,
        headers={"Cache-Control": "public, max-age=86400"},
    )
