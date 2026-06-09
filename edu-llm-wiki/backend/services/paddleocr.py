"""PaddleOCR-VL service for high-quality document parsing.

Uses Baidu AI Studio PaddleOCR-VL-1.6 API to extract structured markdown
from documents (PDF/images). Stores parsed results as sidecar data
alongside the source file in `<source_name>.parsed/` directory.
"""

import asyncio
import hashlib
import json
import re
import time
from pathlib import Path
from typing import Literal
from urllib.parse import quote

import requests

JobStatus = Literal["pending", "running", "done", "failed", "not_started"]


def _get_settings():
    """Load PaddleOCR settings from .env."""
    from config import settings
    return {
        "token": getattr(settings, "paddleocr_token", "") or "",
        "model": getattr(settings, "paddleocr_model", "PaddleOCR-VL-1.6") or "PaddleOCR-VL-1.6",
        "use_doc_orientation": getattr(settings, "paddleocr_orientation", False),
        "use_doc_unwarping": getattr(settings, "paddleocr_unwarping", False),
        "use_chart_recognition": getattr(settings, "paddleocr_chart", False),
    }


def _parsed_dir(sources_root: Path, source_filename: str) -> Path:
    """Get sidecar directory for parsed outputs.

    Layout: <sources_root>/<source_filename>.parsed/
    """
    return sources_root / f"{source_filename}.parsed"


def get_parse_status(source_filename: str, *, project_id: str = "default") -> dict:
    """Return current parse status of a source file.

    Returns: {filename, status, page_count, image_count, error, markdown_path}
    status ∈ {not_started, pending, running, done, failed}
    """
    from storage.wiki_store import sources_path

    sp = sources_path(project_id)
    src = sp / source_filename
    pd = _parsed_dir(sp, source_filename)
    status_file = pd / "status.json"
    md_file = pd / "document.md"

    result = {
        "filename": source_filename,
        "status": "not_started",
        "page_count": 0,
        "image_count": 0,
        "error": None,
        "markdown_path": None,
    }

    if not pd.exists():
        return result

    if status_file.exists():
        try:
            data = json.loads(status_file.read_text(encoding="utf-8"))
            result["status"] = data.get("status", "not_started")
            result["page_count"] = data.get("page_count", 0)
            result["image_count"] = data.get("image_count", 0)
            result["error"] = data.get("error")
            result["job_id"] = data.get("job_id")
        except Exception:
            pass

    if md_file.exists():
        result["markdown_path"] = _parsed_doc_url(source_filename, project_id=project_id)

    return result


def list_all_statuses(*, project_id: str = "default") -> list[dict]:
    """Return parse status for every source file."""
    from storage.wiki_store import sources_path

    sp = sources_path(project_id)
    if not sp.exists():
        return []
    statuses = []
    for entry in sp.iterdir():
        if entry.is_file() and not entry.name.endswith(".parsed") and not entry.name.startswith("."):
            statuses.append(get_parse_status(entry.name, project_id=project_id))
    return statuses


def _write_status(parsed_dir: Path, status: JobStatus, **extra):
    parsed_dir.mkdir(parents=True, exist_ok=True)
    data = {"status": status, "updated": time.time(), **extra}
    (parsed_dir / "status.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _submit_job(file_path: Path) -> str:
    """Submit a file to PaddleOCR API and return the job ID."""
    cfg = _get_settings()
    if not cfg["token"]:
        raise RuntimeError("PaddleOCR token not configured. Set it in Settings → Document Parsing.")

    url = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"
    headers = {"Authorization": f"bearer {cfg['token']}"}
    optional_payload = {
        "useDocOrientationClassify": cfg["use_doc_orientation"],
        "useDocUnwarping": cfg["use_doc_unwarping"],
        "useChartRecognition": cfg["use_chart_recognition"],
    }
    data = {
        "model": cfg["model"],
        "optionalPayload": json.dumps(optional_payload),
    }
    with open(file_path, "rb") as f:
        files = {"file": f}
        r = requests.post(url, headers=headers, data=data, files=files, timeout=120)
    if r.status_code != 200:
        raise RuntimeError(f"PaddleOCR submit failed ({r.status_code}): {r.text[:200]}")
    payload = r.json()
    if payload.get("code") != 0:
        raise RuntimeError(f"PaddleOCR submit error: {payload.get('msg')}")
    return payload["data"]["jobId"]


def _poll_job(job_id: str, max_polls: int = 360, poll_interval: float = 5.0) -> dict:
    """Poll until done/failed. Returns full job data dict on success."""
    cfg = _get_settings()
    url = f"https://paddleocr.aistudio-app.com/api/v2/ocr/jobs/{job_id}"
    headers = {"Authorization": f"bearer {cfg['token']}"}

    for _ in range(max_polls):
        r = requests.get(url, headers=headers, timeout=60)
        if r.status_code != 200:
            raise RuntimeError(f"PaddleOCR poll failed ({r.status_code}): {r.text[:200]}")
        payload = r.json()
        if payload.get("code") != 0:
            raise RuntimeError(f"PaddleOCR poll error: {payload.get('msg')}")
        data = payload.get("data", {})
        state = data.get("state")
        if state == "done":
            return data
        if state == "failed":
            raise RuntimeError(f"PaddleOCR job failed: {data.get('errorMsg')}")
        time.sleep(poll_interval)
    raise RuntimeError("PaddleOCR job timed out")


def _fetch_results(json_url: str) -> list[dict]:
    """Fetch and parse the jsonl result file. Returns list of layout-parsed results."""
    r = requests.get(json_url, timeout=180)
    r.raise_for_status()
    out = []
    for line in r.text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            out.extend(entry.get("result", {}).get("layoutParsingResults", []))
        except json.JSONDecodeError:
            continue
    return out


def _parsed_doc_url(source_filename: str, *, project_id: str = "default") -> str:
    return f"/api/ingest/sources/{quote(source_filename)}/parsed-doc?project_id={quote(project_id)}"


def _parsed_image_url(source_filename: str, image_filename: str, *, project_id: str = "default") -> str:
    return (
        f"/api/ingest/sources/{quote(source_filename)}/parsed-image/"
        f"{quote(image_filename)}?project_id={quote(project_id)}"
    )


def _local_image_url_from_src(source_filename: str, src: str, *, project_id: str = "default") -> str | None:
    """Map OCR image references like imgs/foo.jpg to the parsed-image route."""
    if not src or src.startswith(("http://", "https://", "data:", "/api/")):
        return None

    path = Path(src)
    filename = path.name
    if not filename:
        return None
    return _parsed_image_url(source_filename, filename, project_id=project_id)


def rewrite_parsed_markdown_assets(markdown: str, source_filename: str, *, project_id: str = "default") -> str:
    """Rewrite Markdown and HTML image references in a parsed document."""

    def _md_repl(match: re.Match) -> str:
        alt = match.group(1) or ""
        src = match.group(2).strip()
        local_url = _local_image_url_from_src(source_filename, src, project_id=project_id)
        if local_url:
            return f"![{alt}]({local_url})"
        return match.group(0)

    def _html_repl(match: re.Match) -> str:
        quote_char = match.group(1)
        src = match.group(2).strip()
        local_url = _local_image_url_from_src(source_filename, src, project_id=project_id)
        if local_url:
            return f'src={quote_char}{local_url}{quote_char}'
        return match.group(0)

    markdown = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", _md_repl, markdown)
    markdown = re.sub(r"""src=(["'])([^"']+)\1""", _html_repl, markdown, flags=re.IGNORECASE)
    return markdown


def _rewrite_image_paths(markdown: str, image_url_map: dict[str, str]) -> str:
    """Rewrite PaddleOCR image references to local /api routes."""

    def _repl(match: re.Match) -> str:
        alt = match.group(1) or ""
        orig_path = match.group(2)
        filename = Path(orig_path).name
        local_url = image_url_map.get(orig_path) or image_url_map.get(filename)
        if local_url:
            return f"![{alt}]({local_url})"
        return match.group(0)

    return re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", _repl, markdown)


async def _run_parse(source_filename: str, *, project_id: str = "default") -> dict:
    """Run the full PaddleOCR pipeline and persist sidecar data.

    Returns status dict.
    """
    from storage.wiki_store import sources_path, wiki_path

    sp = sources_path(project_id)
    src = sp / source_filename
    if not src.exists():
        return {"status": "failed", "error": f"File not found: {source_filename}"}

    pd = _parsed_dir(sp, source_filename)
    pd.mkdir(parents=True, exist_ok=True)

    wp = wiki_path(project_id)
    media_root = wp / "media"
    media_root.mkdir(parents=True, exist_ok=True)

    try:
        _write_status(pd, "pending")
        job_id = await asyncio.to_thread(_submit_job, src)
        _write_status(pd, "running", job_id=job_id)
        result = await asyncio.to_thread(_poll_job, job_id)
        json_url = result.get("resultUrl", {}).get("jsonUrl")
        if not json_url:
            raise RuntimeError("PaddleOCR result URL missing")

        parsed_pages = await asyncio.to_thread(_fetch_results, json_url)
        if not parsed_pages:
            raise RuntimeError("PaddleOCR returned no parsed pages")

        # Save images locally + build URL map
        page_imgs_dir = pd / "imgs"
        page_imgs_dir.mkdir(exist_ok=True)
        image_url_map: dict[str, str] = {}
        image_count = 0
        for page_idx, page in enumerate(parsed_pages):
            md = page.get("markdown", {})
            for orig_path, img_url in (md.get("images") or {}).items():
                try:
                    img_data = await asyncio.to_thread(lambda u=img_url: requests.get(u, timeout=60).content)
                    img_filename = Path(orig_path).name
                    (page_imgs_dir / img_filename).write_bytes(img_data)
                    image_url_map[orig_path] = _parsed_image_url(source_filename, img_filename, project_id=project_id)
                    image_url_map[img_filename] = image_url_map[orig_path]
                    image_url_map[f"imgs/{img_filename}"] = image_url_map[orig_path]
                    image_count += 1
                except Exception:
                    continue
            for img_name, img_url in (page.get("outputImages") or {}).items():
                try:
                    img_data = await asyncio.to_thread(lambda u=img_url: requests.get(u, timeout=60).content)
                    fname = f"{img_name}_{page_idx}.jpg"
                    (page_imgs_dir / fname).write_bytes(img_data)
                    image_url_map[img_name] = _parsed_image_url(source_filename, fname, project_id=project_id)
                    image_url_map[fname] = image_url_map[img_name]
                    image_url_map[f"imgs/{fname}"] = image_url_map[img_name]
                    image_count += 1
                except Exception:
                    continue

        # Build combined markdown
        md_parts = []
        for page_idx, page in enumerate(parsed_pages):
            md = page.get("markdown", {})
            text = md.get("text", "")
            text = _rewrite_image_paths(text, image_url_map)
            text = rewrite_parsed_markdown_assets(text, source_filename, project_id=project_id)
            md_parts.append(f"## Page {page_idx + 1}\n\n{text}")
        combined = "\n\n---\n\n".join(md_parts)
        (pd / "document.md").write_text(combined, encoding="utf-8")

        _write_status(pd, "done", page_count=len(parsed_pages), image_count=image_count, job_id=job_id)
        return {"status": "done", "page_count": len(parsed_pages), "image_count": image_count}
    except Exception as e:
        _write_status(pd, "failed", error=str(e))
        return {"status": "failed", "error": str(e)}


async def parse_source_async(source_filename: str, *, project_id: str = "default") -> dict:
    """Public entrypoint: parse a single source file via PaddleOCR-VL."""
    return await _run_parse(source_filename, project_id=project_id)


async def parse_all_pending(*, project_id: str = "default", file_exts: set[str] | None = None) -> list[dict]:
    """Parse all sources that don't yet have a successful parse result.

    file_exts: optional whitelist of extensions to consider (default: pdf + image formats).
    """
    from storage.wiki_store import sources_path

    if file_exts is None:
        file_exts = {".pdf", ".png", ".jpg", ".jpeg"}

    sp = sources_path(project_id)
    if not sp.exists():
        return []

    results = []
    for f in sp.iterdir():
        if not f.is_file():
            continue
        if f.suffix.lower() not in file_exts:
            continue
        st = get_parse_status(f.name, project_id=project_id)
        if st["status"] in ("done", "pending", "running"):
            continue
        results.append(await parse_source_async(f.name, project_id=project_id))
    return results
