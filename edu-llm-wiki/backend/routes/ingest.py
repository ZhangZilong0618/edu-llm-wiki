"""API routes for document ingestion."""

import asyncio
import hashlib
import json
import mimetypes
import os
import re
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from models.wiki import IngestRequest, IngestResult
from services.ingest_engine import run_ingest, run_ingest_batch_streaming, run_ingest_streaming
from storage.wiki_store import (
    delete_wiki_page,
    ensure_dirs,
    list_wiki_pages,
    read_source_manifest,
    read_wiki_page,
    rebuild_index,
    remove_source_manifest,
    sources_path,
    wiki_path,
)

router = APIRouter(prefix="/api/ingest", tags=["ingest"])


SUPPORTED_UPLOAD_EXTENSIONS = {".pdf", ".docx", ".pptx", ".xlsx", ".xls", ".md", ".txt", ".markdown", ".rst"}


def _safe_source_stem(filename: str) -> str:
    return filename.rsplit(".", 1)[0].replace("/", "_").replace("\\", "_")


def _compact_text(value: str) -> str:
    return re.sub(r"[\W_]+", "", value.lower(), flags=re.UNICODE)


def _source_keywords(filename: str) -> set[str]:
    stem = _safe_source_stem(filename)
    cleaned = re.sub(r"第[一二三四五六七八九十0-9]+讲", "", stem)
    keywords = {stem, cleaned}
    keywords.update(part for part in re.split(r"[\s._\-]+", cleaned) if len(part) >= 2)
    for phrase in re.findall(r"[\u4e00-\u9fff]{2,}", cleaned):
        keywords.add(phrase)
        keywords.update(phrase[i:i + 2] for i in range(len(phrase) - 1))
    return {kw for kw in keywords if kw and kw not in {"讲义", "课件", "性能"}}


def _extract_wikilinks(markdown: str) -> set[str]:
    links: set[str] = set()
    for link in re.findall(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]", markdown):
        normalized = link.strip()
        if normalized:
            links.add(normalized if normalized.endswith(".md") else f"{normalized}.md")
    return links


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

    content = await file.read()
    await asyncio.to_thread(dest.write_bytes, content)

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
    """Delete a source file."""
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    sp = sources_path(project_id)
    file_path = sp / filename
    if file_path.exists():
        file_path.unlink()
        return {"status": "deleted"}
    raise HTTPException(status_code=404, detail="File not found")


@router.delete("/sources/{filename}/wiki")
async def delete_source_wiki(filename: str, project_id: str = Query("default")):
    """Delete wiki pages generated from a source file without deleting the source file."""
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    source_stem = _safe_source_stem(filename)
    source_summary_paths = {
        f"sources/{source_stem}.md",
        f"source/{source_stem}.md",
    }
    filename_compact = _compact_text(filename)
    stem_compact = _compact_text(source_stem)
    keywords = _source_keywords(filename)

    manifest = read_source_manifest(project_id=project_id)
    candidates: set[str] = set(manifest.get(filename, []))
    matched_source_pages: list[dict] = []
    matched_created_times: set[str] = set()
    source_aliases: set[str] = {filename}

    pages = []
    for page in list_wiki_pages(project_id=project_id):
        page_data = read_wiki_page(page["path"], project_id=project_id)
        if not page_data:
            continue
        pages.append(page_data)
        source_values = {str(src) for src in (page_data.get("sources", []) or [])}
        title = str(page_data.get("title", ""))
        path = str(page_data.get("path", ""))
        searchable = "\n".join([title, path, *source_values])
        searchable_compact = _compact_text(searchable)
        exact_source_match = (
            filename in source_values
            or path in source_summary_paths
            or filename_compact in searchable_compact
            or stem_compact in searchable_compact
        )
        if exact_source_match:
            candidates.add(path)
            source_aliases.update(source_values)
            if page_data.get("page_type") == "source":
                matched_source_pages.append(page_data)
                if page_data.get("created"):
                    matched_created_times.add(str(page_data["created"]))

    # Old imports sometimes created an extra source summary with an English alias
    # instead of the real PDF filename. Link it back by timestamp plus source keywords.
    for page_data in pages:
        if page_data.get("page_type") != "source" or not page_data.get("created"):
            continue
        if str(page_data["created"]) not in matched_created_times:
            continue
        text = "\n".join([str(page_data.get("title", "")), str(page_data.get("content", ""))])
        if any(keyword in text for keyword in keywords):
            candidates.add(str(page_data["path"]))
            source_aliases.update(str(src) for src in (page_data.get("sources", []) or []))
            matched_source_pages.append(page_data)

    for source_page in matched_source_pages:
        candidates.update(_extract_wikilinks(str(source_page.get("content", ""))))

    for page_data in pages:
        path = str(page_data["path"])
        source_values = {str(src) for src in (page_data.get("sources", []) or [])}
        if source_values & source_aliases:
            candidates.add(path)

    deleted: list[str] = []
    for path in sorted(candidates):
        if delete_wiki_page(path, project_id=project_id):
            deleted.append(path)

    cache_file = wiki_path(project_id) / ".cache" / (hashlib.md5(filename.encode()).hexdigest() + ".hash")
    cache_deleted = False
    if cache_file.exists():
        cache_file.unlink()
        cache_deleted = True

    remove_source_manifest(filename, project_id=project_id)
    rebuild_index(project_id=project_id)

    return {
        "status": "deleted",
        "source": filename,
        "deleted_pages": deleted,
        "deleted_count": len(deleted),
        "cache_deleted": cache_deleted,
    }


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


def _safe_parsed_filename(source_filename: str) -> str:
    if ".." in source_filename or "/" in source_filename or "\\" in source_filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    return source_filename


@router.post("/sources/{filename}/parse")
async def start_parse(filename: str, project_id: str = Query("default")):
    """Trigger a PaddleOCR-VL parse for a single source file.

    Returns immediately with the current job status. The parse runs
    asynchronously; poll /api/ingest/sources/{filename}/parse-status
    for progress.
    """
    from services.paddleocr import parse_source_async

    _safe_parsed_filename(filename)
    sp = sources_path(project_id)
    if not (sp / filename).exists():
        raise HTTPException(status_code=404, detail="File not found")

    import asyncio
    asyncio.create_task(parse_source_async(filename, project_id=project_id))

    from services.paddleocr import get_parse_status
    return get_parse_status(filename, project_id=project_id)


@router.get("/sources/{filename}/parse-status")
async def get_parse_status(filename: str, project_id: str = Query("default")):
    """Get the PaddleOCR parse status of a source file."""
    from services.paddleocr import get_parse_status as _status
    _safe_parsed_filename(filename)
    return _status(filename, project_id=project_id)


@router.get("/parse-statuses")
async def get_all_parse_statuses(project_id: str = Query("default")):
    """Get parse status for all source files."""
    from services.paddleocr import list_all_statuses
    return list_all_statuses(project_id=project_id)


@router.post("/parse-all-pending")
async def parse_all_pending(project_id: str = Query("default")):
    """Trigger PaddleOCR parsing for all sources not yet successfully parsed."""
    from services.paddleocr import parse_all_pending, list_all_statuses

    import asyncio
    asyncio.create_task(parse_all_pending(project_id=project_id))
    return {"status": "started", "files": list_all_statuses(project_id=project_id)}


@router.get("/sources/{filename}/parsed-doc")
async def get_parsed_doc(filename: str, project_id: str = Query("default")):
    """Return the parsed markdown for a source file as JSON.

    The markdown references images via /api/ingest/sources/{filename}/parsed-image/{img}
    """
    from services.paddleocr import _parsed_dir, rewrite_parsed_markdown_assets

    _safe_parsed_filename(filename)
    sp = sources_path(project_id)
    pd = _parsed_dir(sp, filename)
    md_path = pd / "document.md"
    if not md_path.exists():
        raise HTTPException(status_code=404, detail="Parsed document not available. Run parse first.")
    content = md_path.read_text(encoding="utf-8")
    content = rewrite_parsed_markdown_assets(content, filename, project_id=project_id)
    if len(content) > 200000:
        content = content[:200000] + "\n\n[Truncated...]"
    return {
        "filename": filename,
        "content": content,
    }


@router.get("/sources/{filename}/parsed-image/{image_name}")
async def get_parsed_image(filename: str, image_name: str, project_id: str = Query("default")):
    """Serve an image from the parsed document's image directory."""
    from services.paddleocr import _parsed_dir

    _safe_parsed_filename(filename)
    if ".." in image_name or "/" in image_name or "\\" in image_name:
        raise HTTPException(status_code=400, detail="Invalid image name")
    sp = sources_path(project_id)
    pd = _parsed_dir(sp, filename)
    img_path = pd / "imgs" / image_name
    if not img_path.exists() or not img_path.is_file():
        raise HTTPException(status_code=404, detail="Image not found")
    mime_type, _ = mimetypes.guess_type(str(img_path))
    if not mime_type:
        mime_type = "application/octet-stream"
    return FileResponse(
        path=str(img_path),
        media_type=mime_type,
        headers={"Cache-Control": "public, max-age=86400"},
    )
