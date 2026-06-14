"""Build a structured `parsed.json` index from an existing `document.md`.

The parsed.json is the sidecar that downstream stages (citation validation,
graph linking, ref-aware chunking) rely on. We DO NOT re-run PaddleOCR here —
we slice the already-produced `document.md` into per-page records and
record byte offsets for fast quote lookup.

Sidecar layout:
    <sources_root>/<file>.parsed/
        document.md         # raw combined markdown (already produced)
        status.json         # PaddleOCR status (already produced)
        imgs/               # extracted images (already produced)
        parsed.json         # ← this module writes this
        parsed.sha256       # checksum of document.md used to build it

Schema:
    {
      "file": "原文件.pdf",
      "sha256": "...",                  # sha of document.md at build time
      "page_count": 31,
      "image_count": 65,
      "pages": [
        {
          "page": 1,
          "md": "## Page 1\\n\\n…",      # page markdown, image URLs preserved
          "text_offset_start": 0,        # offset of `md` inside the source document.md
          "text_offset_end": 1234,
          "images": [                    # images that appear on this page
            {"name": "p1_img0.jpg", "src": "/api/ingest/sources/<file>/parsed-image/p1_img0.jpg"}
          ],
          "char_count": 980              # length of md
        },
        ...
      ],
      "fulltext": "## Page 1\\n\\n…\\n\\n---\\n\\n## Page 2\\n\\n…"
                   # also stored so find_quote can do a single substring scan
    }
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import quote as _urlquote


PAGE_HEADER_RE = re.compile(r"^## Page (\d+)\s*$", re.MULTILINE)
PAGE_DELIMITER = "\n---\n"
IMG_REF_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
HTML_IMG_RE = re.compile(r"<img\b[^>]*src=[\"']([^\"']+)[\"']", re.IGNORECASE)
PARSED_JSON_NAME = "parsed.json"
SHA_FILE_NAME = "parsed.sha256"


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _image_url(source_filename: str, image_name: str) -> str:
    return f"/api/ingest/sources/{_urlquote(source_filename)}/parsed-image/{_urlquote(image_name)}"


def _extract_image_names(md_chunk: str) -> list[str]:
    """Pull out just the image basenames from a markdown chunk.

    Handles both markdown image syntax (`![alt](url)`) and inline HTML
    (`<img src="...">`) — PaddleOCR mixes the two depending on layout.
    We strip any URL prefix and the query string — only the basename is
    persisted. The renderer reconstructs the URL at request time.
    """
    names: list[str] = []
    for m in IMG_REF_RE.finditer(md_chunk):
        src = m.group(1).strip()
        if src.startswith("http://") or src.startswith("https://"):
            continue
        base = _basename_with_query(src)
        if base and base not in names:
            names.append(base)
    for m in HTML_IMG_RE.finditer(md_chunk):
        src = m.group(1).strip()
        if src.startswith("http://") or src.startswith("https://"):
            continue
        base = _basename_with_query(src)
        if base and base not in names:
            names.append(base)
    return names


def _basename_with_query(src: str) -> str:
    """Return the last path segment, stripping any `?query=...` suffix."""
    no_query = src.split("?", 1)[0]
    return no_query.rsplit("/", 1)[-1]


def _split_pages(combined_md: str) -> list[tuple[int, int, str]]:
    """Split `combined_md` into [(page_no, start_offset, md_chunk), …].

    PaddleOCR writes pages as `## Page N\\n\\n…` joined by `\\n---\\n`. We walk
    the document and track the byte (well, codepoint) offset of each chunk
    in the original string. The first page is whatever precedes the first
    `\n---\n` separator; its `## Page N` header is preserved inside the chunk
    so callers can see the page number without re-parsing the header.
    """
    pages: list[tuple[int, int, str]] = []
    cursor = 0
    page_no = 1
    while True:
        sep = combined_md.find(PAGE_DELIMITER, cursor)
        if sep == -1:
            chunk = combined_md[cursor:]
            pages.append((page_no, cursor, chunk))
            break
        chunk = combined_md[cursor:sep]
        pages.append((page_no, cursor, chunk))
        cursor = sep + len(PAGE_DELIMITER)
        page_no += 1
    return pages


def build_parsed_index(
    sources_root: Path,
    source_filename: str,
    *,
    force: bool = False,
) -> dict:
    """Build (or rebuild) parsed.json for `source_filename`.

    Returns the parsed.json payload. Idempotent: if the SHA of document.md
    matches the recorded one and `force=False`, the existing parsed.json is
    returned unchanged.
    """
    pd = sources_root / f"{source_filename}.parsed"
    md_path = pd / "document.md"
    if not md_path.exists():
        raise FileNotFoundError(f"document.md not found for {source_filename}")

    parsed_path = pd / PARSED_JSON_NAME
    sha_path = pd / SHA_FILE_NAME
    current_sha = _file_sha256(md_path)

    if not force and _cache_is_valid(sha_path, parsed_path, current_sha):
        cached = _load_cached(parsed_path)
        if cached is not None:
            return cached

    payload = _build_payload(sources_root, source_filename, md_path, current_sha)
    _write_payload(parsed_path, sha_path, payload, current_sha)
    return payload


def _build_payload(sources_root: Path, source_filename: str, md_path: Path, sha: str) -> dict:
    combined_md = md_path.read_text(encoding="utf-8")
    image_total = _count_images(sources_root / f"{source_filename}.parsed" / "imgs")
    pages_out = [_build_page_record(pno, start, chunk, source_filename)
                 for pno, start, chunk in _split_pages(combined_md)]
    return {
        "file": source_filename,
        "sha256": sha,
        "page_count": len(pages_out),
        "image_count": image_total,
        "pages": pages_out,
    }


def _write_payload(parsed_path: Path, sha_path: Path, payload: dict, sha: str) -> None:
    parsed_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    sha_path.write_text(sha, encoding="utf-8")


def _cache_is_valid(sha_path: Path, parsed_path: Path, current_sha: str) -> bool:
    if not (parsed_path.exists() and sha_path.exists()):
        return False
    try:
        recorded = sha_path.read_text(encoding="utf-8").strip()
    except OSError:
        return False
    return recorded == current_sha


def _load_cached(parsed_path: Path) -> dict | None:
    try:
        return json.loads(parsed_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None  # corrupted — rebuild


def _count_images(imgs_dir: Path) -> int:
    if not imgs_dir.exists():
        return 0
    return sum(1 for f in imgs_dir.iterdir() if f.is_file())


def _build_page_record(page_no: int, start: int, chunk: str, source_filename: str) -> dict:
    body = chunk.strip()
    if body.startswith(f"## Page {page_no}"):
        nl = body.find("\n")
        if nl != -1:
            body = body[nl + 1:].lstrip()
    image_names = _extract_image_names(chunk)
    return {
        "page": page_no,
        "md": body,
        "text_offset_start": start,
        "text_offset_end": start + len(chunk),
        "images": [
            {"name": n, "src": _image_url(source_filename, n)}
            for n in image_names
        ],
        "char_count": len(body),
    }


def find_quote(parsed: dict, page: int, quote: str) -> list[list[int]]:
    """Return [[start, end], …] offsets of `quote` inside pages[page-1].md.

    Offsets are within that page's `md` field, not the combined document.
    If no exact match is found, returns an empty list — the caller can fall
    back to a fuzzy match elsewhere.
    """
    if page < 1 or page > parsed.get("page_count", 0):
        return []
    body = parsed["pages"][page - 1]["md"]
    out: list[list[int]] = []
    start = 0
    while True:
        idx = body.find(quote, start)
        if idx == -1:
            return out
        out.append([idx, idx + len(quote)])
        start = idx + max(len(quote), 1)
        if len(out) >= 5:
            return out


def load_parsed_index(sources_root: Path, source_filename: str) -> dict | None:
    """Load an existing parsed.json, or None if it doesn't exist."""
    pd = sources_root / f"{source_filename}.parsed"
    p = pd / PARSED_JSON_NAME
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
