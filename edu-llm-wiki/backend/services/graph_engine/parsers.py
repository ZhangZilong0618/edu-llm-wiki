"""Page-level parsers for the learning graph.

These functions read the wiki store and return a normalised ``ParsedPage``
view: identifiers, title, type, content, wikilinks, sources, prerequisites,
and the LLM-emitted ``relationships`` / ``parent_concept`` that the v1 engine
ignored.

Everything downstream of this module is content-agnostic — it operates on
``ParsedPage`` instances only, which makes the pipeline testable without
filesystem I/O.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from services.graph_store import make_node_id
from storage.wiki_store import list_wiki_pages, parse_frontmatter, wiki_path


WIKILINK_RE = re.compile(r"\[\[([^\]|]+?)(?:\|[^\]]+?)?\]\]")

VALID_NODE_TYPES = {
    "concept", "formula", "principle",
    "source", "synthesis", "inquiry", "guide",
}


@dataclass(slots=True)
class Relationship:
    """One LLM-emitted edge in the original analysis document."""
    src: str
    dst: str
    rel_type: str  # prerequisite | derives | applies_to | related
    description: str = ""


@dataclass(slots=True)
class ParsedPage:
    """One wiki page after frontmatter + body have been parsed."""
    node_id: str
    path: str
    title: str
    page_type: str
    content: str
    sources: list[str] = field(default_factory=list)
    prerequisites: list[str] = field(default_factory=list)
    related: list[str] = field(default_factory=list)
    parent_concept: str = ""
    relationships: list[Relationship] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    bloom_level: str | None = None
    difficulty: int | None = None
    estimated_minutes: float | None = None
    content_hash: str = ""


def _normalise_relationships(raw: object) -> list[Relationship]:
    if not isinstance(raw, list):
        return []
    out: list[Relationship] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        src = str(item.get("from") or "").strip()
        dst = str(item.get("to") or "").strip()
        rel = str(item.get("type") or "related").strip()
        desc = str(item.get("description") or "").strip()
        if not src or not dst:
            continue
        if rel not in {"prerequisite", "derives", "applies_to", "related"}:
            rel = "related"
        out.append(Relationship(src=src, dst=dst, rel_type=rel, description=desc))
    return out


def _parse_relationships_field(content: str) -> list[Relationship]:
    """Find a `## Relationships` section the LLM sometimes leaves in pages."""
    match = re.search(
        r"##\s*relationships\s*\n([\s\S]*?)(?=\n##\s+|\Z)",
        content,
        re.IGNORECASE,
    )
    if not match:
        return []
    block = match.group(1)
    out: list[Relationship] = []
    for line in block.splitlines():
        line = line.strip("-* \t")
        if not line:
            continue
        # "Concept A --[prerequisite]--> Concept B: explanation"
        m = re.match(
            r"([^\-\[>]+?)\s*--\[\s*(\w+)\s*\]\s*-->\s*([^\:]+?)(?::\s*(.*))?$",
            line,
        )
        if m:
            out.append(Relationship(
                src=m.group(1).strip(),
                dst=m.group(3).strip(),
                rel_type=m.group(2).strip().lower(),
                description=(m.group(4) or "").strip(),
            ))
    return out


def _related_from_body(content: str) -> list[str]:
    """Extract related-page titles from generated “关联知识/相关概念” sections."""
    out: list[str] = []
    for heading in ("相关知识", "相关概念"):
        pattern = rf"##\s*{heading}\s*\n([\s\S]*?)(?=\n##\s+|\Z)"
        match = re.search(pattern, content, re.IGNORECASE)
        if not match:
            continue
        for raw_line in match.group(1).splitlines():
            line = raw_line.strip("-* \t")
            if not line or line == "待补充":
                continue
            # Generated bullets may contain explanatory text after a colon.
            title = line.split("：", 1)[0].split(":", 1)[0].strip()
            if title and title != "待补充" and title not in out:
                out.append(title)
    return out


def parse_pages(*, project_id: str) -> tuple[dict[str, ParsedPage], dict[str, str]]:
    """Read all wiki pages for ``project_id`` and return them in normalised form.

    Returns a mapping of ``node_id`` to ``ParsedPage`` and a mapping of
    page *title* to ``node_id`` (the LLM names relationships by title, but the
    graph keys by node id, so we need a resolver).
    """
    pages = list_wiki_pages(project_id=project_id)
    wp = wiki_path(project_id)
    out: dict[str, ParsedPage] = {}
    title_to_id: dict[str, str] = {}
    for summary in pages:
        page_path = summary["path"]
        node_id = make_node_id(project_id, page_path)
        full = wp / summary["path"]
        if not full.exists():
            continue
        content = full.read_text(encoding="utf-8")
        front, body = parse_frontmatter(content)
        page_type = str(front.get("type") or summary.get("type") or "concept")
        if page_type not in VALID_NODE_TYPES:
            page_type = "concept"
        parsed = ParsedPage(
            node_id=node_id,
            path=summary["path"],
            title=str(front.get("title") or summary.get("title") or node_id),
            page_type=page_type,
            content=body,
            sources=list(front.get("sources", []) or []),
            prerequisites=[
                p.replace(".md", "").strip()
                for p in (front.get("prerequisites", []) or [])
                if p
            ] + _wikilink_prereqs(body),
            related=_dedupe([
                str(p).replace(".md", "").strip()
                for p in (front.get("related", []) or [])
                if p
            ] + _related_from_body(body)),
            parent_concept=str(front.get("parent_concept") or "").strip(),
            relationships=(
                _normalise_relationships(front.get("relationships"))
                + _parse_relationships_field(body)
            ),
            tags=list(front.get("tags", []) or []),
            bloom_level=front.get("bloom_level"),
            difficulty=front.get("difficulty"),
            estimated_minutes=front.get("estimated_minutes"),
        )
        parsed.content_hash = _hash_content(content)
        out[node_id] = parsed
        title_to_id[parsed.title] = node_id
        title_to_id[parsed.path] = node_id
        title_to_id[parsed.path.replace(".md", "")] = node_id
        title_to_id[parsed.path.removesuffix(".md").split("/")[-1]] = node_id
        # Also key by the file's basename (e.g. `KNN欧氏距离公式`) and its
        # case-insensitive variant.  This makes `[[KNN]]` resolve to the
        # KNN page even when the page title has been enriched with a
        # semantic suffix.  First-registration wins, so any later exact
        # match (above) still takes precedence.
        slug = parsed.path.removesuffix(".md").split("/")[-1]
        title_to_id.setdefault(slug, node_id)
        title_to_id.setdefault(slug.lower(), node_id)
        title_to_id.setdefault(parsed.title.lower(), node_id)
    return out, title_to_id


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return out


def _hash_content(content: str) -> str:
    import hashlib
    return hashlib.sha256(content.encode("utf-8", "replace")).hexdigest()


_WIKILINK_RE = __import__("re").compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")


def _wikilink_prereqs(body: str) -> list[str]:
    """Extract ``[[concepts/Title]]`` wiki-links as prereq hints.

    These are the primary signal when LLM extraction is unavailable
    (offline rebuild, cold start, low-quality source).
    """
    seen: list[str] = []
    for m in _WIKILINK_RE.finditer(body or ""):
        target = m.group(1).strip()
        if not target:
            continue
        target = target.removeprefix("concepts/").removesuffix(".md")
        if target and target not in seen:
            seen.append(target)
    return seen
