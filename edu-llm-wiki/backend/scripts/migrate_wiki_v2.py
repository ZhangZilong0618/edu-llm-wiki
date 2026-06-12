"""One-shot wiki v1 → v2 migration.

Per docs/wiki-redesign.md §6:

  1. Rename folders: queries/ → inquiries/, systems/ → guides/,
     exercises/ → _archive/exercises/ (kept but not rendered).
  2. Frontmatter upgrade: add difficulty / last_reviewed / prerequisites /
     related / common_misconceptions with sensible defaults from existing
     fields and body sections. For type: exercise pages, set type: archived.
     For type: query / type: system pages, rename to inquiry / guide.
  3. Wikilink path rewrite: [[queries/X]] → [[inquiries/X]],
     [[systems/X]] → [[guides/X]]; [[exercises/X]] left as-is.
  4. Update index.md sections to match the new 7-type taxonomy.

Idempotent: every action checks "already done" first and is a no-op
when the target exists or the source is gone. Safe to re-run after a
partial migration.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

import yaml

# Project root layout
ROOT = Path(__file__).resolve().parents[2]  # edu-llm-wiki/
PROJECTS_DIR = ROOT / "data" / "projects"

# v1 → v2 type renames (frontmatter value `type` field)
TYPE_RENAMES: dict[str, str] = {
    "query": "inquiry",
    "system": "guide",
    "exercise": "archived",
}

# v1 → v2 folder renames (relative to wiki root)
FOLDER_RENAMES: dict[str, str] = {
    "queries": "inquiries",
    "systems": "guides",
    "exercises": "_archive/exercises",
}

# v1 → v2 wikilink path rewrite (regex applied to body + frontmatter)
# Captures e.g. [[queries/abc]] or [[queries/abc|alias]]; we keep alias if present.
WIKILINK_RE = re.compile(
    r"\[\[(?P<path>(?:queries|systems|exercises)/[^\]|]+)(?P<alias>\|[^\]]*)?\]\]"
)
WIKILINK_REPLACEMENTS = {
    "queries": "inquiries",
    "systems": "guides",
    # exercises deliberately omitted — left as-is per docs/wiki-redesign.md §6.3
}


def _parse_frontmatter(text: str) -> tuple[dict | None, str]:
    """Return (frontmatter_dict_or_None, body). Tolerant of missing FM."""
    m = re.match(r"^---\n(?P<fm>.*?)\n---\n?(?P<body>.*)", text, re.DOTALL)
    if not m:
        return None, text
    try:
        fm = yaml.safe_load(m.group("fm")) or {}
    except yaml.YAMLError:
        return None, text
    if not isinstance(fm, dict):
        return None, text
    return fm, m.group("body")


def _dump_frontmatter(fm: dict) -> str:
    return "---\n" + yaml.dump(fm, allow_unicode=True, default_flow_style=False) + "---\n"


def _rewrite_wikilinks(text: str) -> str:
    def repl(match: re.Match) -> str:
        path = match.group("path")
        alias = match.group("alias") or ""
        first = path.split("/", 1)[0]
        new_first = WIKILINK_REPLACEMENTS.get(first, first)
        if new_first == first:
            return match.group(0)
        return f"[[{new_first}/{path.split('/', 1)[1]}{alias}]]"

    return WIKILINK_RE.sub(repl, text)


def _extract_section_terms(body: str, headings: list[str]) -> list[str]:
    """Pull `[[wikilink]]` references from the first matching body section."""
    heading_pat = "|".join(re.escape(h) for h in headings)
    m = re.search(
        rf"^##\s*(?:{heading_pat})\s*$\n(?P<body>.*?)(?=^##\s|\Z)",
        body,
        re.MULTILINE | re.DOTALL,
    )
    if not m:
        return []
    refs = re.findall(r"\[\[([^\]|#]+)", m.group("body"))
    return [r.strip() for r in refs if r.strip()]


def _upgrade_frontmatter(fm: dict, body: str) -> dict:
    """Apply v1 → v2 field upgrades. Mutates and returns fm."""
    # Type rename
    fm_type = str(fm.get("type", "")).strip().lower()
    if fm_type in TYPE_RENAMES:
        fm["type"] = TYPE_RENAMES[fm_type]

    # difficulty default 3 (per §6.2)
    if "difficulty" not in fm or fm.get("difficulty") is None:
        fm["difficulty"] = 3

    # last_reviewed default = updated (per §6.2)
    if not fm.get("last_reviewed"):
        fm["last_reviewed"] = fm.get("updated", "") or ""

    # prerequisites from body `## 所属概念` section
    if "prerequisites" not in fm:
        fm["prerequisites"] = _extract_section_terms(body, ["所属概念", "Prerequisites"])

    # related from body `## 相关概念` section
    if "related" not in fm:
        fm["related"] = _extract_section_terms(body, ["相关概念", "Related"])

    # common_misconceptions default [] (per §6.2)
    if "common_misconceptions" not in fm:
        fm["common_misconceptions"] = []

    return fm


def _migrate_one_page(path: Path) -> bool:
    """Migrate a single .md file. Returns True if it was changed."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False

    fm, body = _parse_frontmatter(text)
    if fm is None:
        # No frontmatter — skip silently (matches §6 graceful-degradation principle)
        return False

    new_fm = _upgrade_frontmatter(dict(fm), body)
    new_body = _rewrite_wikilinks(body)

    # Re-emit
    new_text = _dump_frontmatter(new_fm) + "\n" + new_body.lstrip("\n")

    if new_text == text:
        return False
    path.write_text(new_text, encoding="utf-8")
    return True


def _rewrite_index(wiki_dir: Path) -> bool:
    """Update index.md section headers to the v2 7-type taxonomy."""
    index_path = wiki_dir / "index.md"
    if not index_path.exists():
        return False
    text = index_path.read_text(encoding="utf-8")
    new_text = text
    # Map old section names → new ones (only the headings, not the entries)
    heading_renames = {
        "## 问答记录 (Queries)": "## 问答记录 (Inquiries)",
        "## 系统指引 (System)": "## 学习指引 (Guides)",
    }
    for old, new in heading_renames.items():
        new_text = new_text.replace(old, new)
    if new_text == text:
        return False
    index_path.write_text(new_text, encoding="utf-8")
    return True


def _rename_folders(wiki_dir: Path) -> dict[str, str]:
    """Rename v1 folders to v2 destinations. Returns {src: dst} actually moved."""
    moved: dict[str, str] = {}
    for src_name, dst_rel in FOLDER_RENAMES.items():
        src = wiki_dir / src_name
        if not src.exists() or not src.is_dir():
            continue
        dst = wiki_dir / dst_rel
        if dst.exists():
            # Already moved (or destination pre-exists) — leave it alone
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        moved[src_name] = dst_rel
    return moved


def migrate_project(wiki_dir: Path, *, dry_run: bool = False) -> dict:
    """Migrate one project's wiki/. Returns a summary dict."""
    summary = {
        "wiki_dir": str(wiki_dir),
        "folders_moved": {},
        "pages_changed": 0,
        "pages_scanned": 0,
        "index_changed": False,
    }

    if not wiki_dir.exists():
        return summary

    # 1. Rename folders first so pages live at their new paths when we rewrite
    if dry_run:
        for src in FOLDER_RENAMES:
            if (wiki_dir / src).exists():
                summary["folders_moved"][src] = FOLDER_RENAMES[src]
    else:
        summary["folders_moved"] = _rename_folders(wiki_dir)

    # 2. Walk every .md under wiki/ (excluding system files) and migrate page
    excluded = {"purpose.md", "schema.md", "index.md", "log.md"}
    for md in sorted(wiki_dir.rglob("*.md")):
        if md.name in excluded:
            continue
        summary["pages_scanned"] += 1
        if dry_run:
            # Cheap "would change?" probe: read + check if rewrite differs
            text = md.read_text(encoding="utf-8")
            fm, body = _parse_frontmatter(text)
            if fm is None:
                continue
            new_fm = _upgrade_frontmatter(dict(fm), body)
            new_body = _rewrite_wikilinks(body)
            if (_dump_frontmatter(new_fm) + "\n" + new_body.lstrip("\n")) != text:
                summary["pages_changed"] += 1
        else:
            if _migrate_one_page(md):
                summary["pages_changed"] += 1

    # 3. Update index.md headings
    if dry_run:
        ip = wiki_dir / "index.md"
        if ip.exists():
            t = ip.read_text(encoding="utf-8")
            for old in ("## 问答记录 (Queries)", "## 系统指引 (System)"):
                if old in t:
                    summary["index_changed"] = True
                    break
    else:
        summary["index_changed"] = _rewrite_index(wiki_dir)

    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--projects-dir",
        type=Path,
        default=PROJECTS_DIR,
        help=f"Projects root (default: {PROJECTS_DIR})",
    )
    parser.add_argument(
        "--project",
        action="append",
        default=[],
        help="Limit to one project name (repeatable). Default: all under projects-dir.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would change without touching the filesystem.",
    )
    args = parser.parse_args(argv)

    projects_dir: Path = args.projects_dir
    if not projects_dir.exists():
        print(f"error: projects dir not found: {projects_dir}", file=sys.stderr)
        return 2

    if args.project:
        names = args.project
    else:
        names = sorted(p.name for p in projects_dir.iterdir() if p.is_dir())

    mode = "DRY-RUN" if args.dry_run else "APPLY"
    print(f"[migrate_wiki_v2] {mode} — scanning {len(names)} project(s) under {projects_dir}")

    total_pages_changed = 0
    for name in names:
        wiki_dir = projects_dir / name / "wiki"
        summary = migrate_project(wiki_dir, dry_run=args.dry_run)
        marker = "*" if (summary["pages_changed"] or summary["folders_moved"] or summary["index_changed"]) else " "
        print(
            f"  {marker} {name:>12} | folders: {len(summary['folders_moved'])} "
            f"| pages: {summary['pages_changed']}/{summary['pages_scanned']} changed "
            f"| index: {'yes' if summary['index_changed'] else 'no'}"
        )
        if summary["folders_moved"]:
            for src, dst in summary["folders_moved"].items():
                print(f"      {src}/  →  {dst}/")
        total_pages_changed += summary["pages_changed"]

    print(f"[migrate_wiki_v2] done. total page changes: {total_pages_changed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
