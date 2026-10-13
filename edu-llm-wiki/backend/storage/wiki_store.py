"""Wiki store: read/write markdown files with YAML frontmatter."""

import hashlib
import json
import os
import posixpath
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from pathlib import PurePosixPath
from urllib.parse import unquote

import yaml

from config import settings


def wiki_path(project_id: str = "default") -> Path:
    validate_project_id(project_id)
    return Path(settings.projects_dir) / project_id / "wiki"


def is_private_learner_page_path(relative_path: str) -> bool:
    """Return whether a path addresses an internal learner snapshot."""
    candidate = str(relative_path or "").replace("\\", "/")
    for _ in range(3):
        decoded = unquote(candidate)
        if decoded == candidate:
            break
        candidate = decoded.replace("\\", "/")
    parts = PurePosixPath(posixpath.normpath(candidate)).parts
    return len(parts) >= 2 and parts[0] == "learning" and parts[1] == "learners"


def sources_path(project_id: str = "default") -> Path:
    validate_project_id(project_id)
    return Path(settings.projects_dir) / project_id / "sources"


_INDEX_SECTION_NAMES: dict[str, str] = {
    "concept": "## 概念 (Concepts)",
    "fact": "## 事实 (Facts)",
    "formula": "## 公式 (Formulas)",
    "principle": "## 原理 (Principles)",
}


def _teaching_groups() -> dict[str, dict[str, object]]:
    """Return the TeachingObject taxonomy from the ontology source of truth."""
    from services.ontology_v2 import TEACHING_CLASS_GROUPS, TEACHING_CLASS_LABELS

    # Keep the directory grouping and the class-page labels in one source of
    # truth.  ``classes`` deliberately remains a tuple so callers can
    # use it as a stable ordering contract.  If the ontology cannot load,
    # fail loudly instead of creating an incomplete Wiki taxonomy.
    return {
        name: {**group, "labels": {
            cls: TEACHING_CLASS_LABELS.get(cls, (cls, ""))[0]
            for cls in group.get("classes", ())
        }}
        for name, group in TEACHING_CLASS_GROUPS.items()
    }


def _ensure_teaching_index(wp: Path) -> None:
    """Materialize the ontology taxonomy as stable wiki directory pages."""
    teaching = wp / "teaching"
    teaching.mkdir(parents=True, exist_ok=True)
    groups = _teaching_groups()
    rows: list[str] = []
    managed_start = "<!-- ontology-managed:teaching-index:start -->"
    managed_end = "<!-- ontology-managed:teaching-index:end -->"
    group_start = "<!-- ontology-managed:group-classes:start -->"
    group_end = "<!-- ontology-managed:group-classes:end -->"

    _migrate_managed_teaching_pages(teaching, groups)

    def replace_block(body: str, start: str, end: str, replacement: str) -> str:
        pattern = re.compile(rf"{re.escape(start)}.*?{re.escape(end)}", re.DOTALL)
        block = f"{start}\n{replacement.rstrip()}\n{end}"
        if pattern.search(body):
            return pattern.sub(block, body, count=1)
        return body.rstrip() + "\n\n" + block + "\n"

    def write_or_sync_group_page(page: Path, group_name: str, label: str, classes: tuple[str, ...]) -> None:
        class_lines = "\n".join(f"- `{name}`" for name in classes) or "- （待补充）"
        if page.exists():
            raw = page.read_text(encoding="utf-8")
            fm, body = parse_frontmatter(raw)
        else:
            fm, body = {}, f"# {label}\n\n本目录对应 EDU-ONTO v2 的 `{group_name}`。\n"
        fm.update({"title": label, "type": "teaching_object_group", "ontology_class": group_name, "auto_managed": True})
        # Migrate the old generated list even when a managed block already
        # exists.  Earlier versions could write the marker around a page that
        # still had the legacy list, producing two identical "包含对象"
        # sections.  Remove only an exact list of ontology class names and
        # leave any teacher-authored prose intact.  The list inside the
        # managed block is deliberately preserved and replaced below.
        known_classes = {
            class_name
            for known_group in groups.values()
            for class_name in known_group.get("classes", ())
        }
        managed_match = re.search(
            rf"{re.escape(group_start)}.*?{re.escape(group_end)}",
            body,
            flags=re.DOTALL,
        )
        legacy_pattern = re.compile(
            r"(?m)^## 包含对象\n((?:- `[^`\n]+`\n?)+)"
        )
        for legacy in reversed(list(legacy_pattern.finditer(body))):
            if managed_match and managed_match.start() <= legacy.start() < managed_match.end():
                continue
            names = re.findall(r"(?m)^- `([^`]+)`$", legacy.group(1))
            if names and all(name in known_classes for name in names):
                body = body[:legacy.start()] + body[legacy.end():]
        body = replace_block(body, group_start, group_end, "## 包含对象\n" + class_lines)
        page.write_text(make_frontmatter(fm) + "\n" + body.strip() + "\n", encoding="utf-8")

    for group_name, group in groups.items():
        folder = str(group["folder"])
        label = str(group["zh"])
        classes = tuple(group.get("classes") or ())
        labels = dict(group.get("labels") or {})
        directory = teaching / folder
        directory.mkdir(parents=True, exist_ok=True)
        page = directory / "index.md"
        write_or_sync_group_page(page, group_name, label, classes)
        # One stable page per ontology class lets the assistant attach
        # projections to a semantic object without putting generated text in
        # authored knowledge pages.  Existing bodies are left intact so a
        # teacher can enrich or replace the generated stub; only the
        # ontology-owned frontmatter is synchronized below.
        for class_name in classes:
            class_page = directory / f"{class_name}.md"
            label = labels.get(class_name, class_name)
            if not class_page.exists():
                class_page.write_text(
                    make_frontmatter({
                        "title": label,
                        "type": "teaching_object",
                        "ontology_class": class_name,
                        "group": group_name,
                        "auto_managed": True,
                    })
                    + f"\n# {label}\n\n"
                    + f"本页对应 EDU-ONTO v2 的 `{class_name}` 类。\n\n"
                    + "页面内容可由教师继续补充；系统只维护结构化元数据和事件投影。\n",
                    encoding="utf-8",
                )
            else:
                # Keep authored Markdown intact while refreshing the
                # ontology-owned frontmatter.  This matters when a class is
                # renamed or moved between TeachingObject groups: the page
                # path is materialized from the new taxonomy, and its
                # metadata must not continue to advertise the old group.
                raw = class_page.read_text(encoding="utf-8")
                existing_fm, existing_body = parse_frontmatter(raw)
                existing_fm.update({
                    "title": label,
                    "type": "teaching_object",
                    "ontology_class": class_name,
                    "group": group_name,
                    "auto_managed": True,
                })
                class_page.write_text(
                    make_frontmatter(existing_fm) + "\n" + existing_body.strip() + "\n",
                    encoding="utf-8",
                )
        rows.append(f"- [{str(group['zh'])}](teaching/{folder}/index.md) (`{group_name}`)")
    root = teaching / "index.md"
    if root.exists():
        raw = root.read_text(encoding="utf-8")
        fm, body = parse_frontmatter(raw)
    else:
        fm, body = {}, "# 教学应用对象\n\nTeachingObject 分类目录（由本体分类派生）。\n"
    fm.update({"title": "教学应用对象", "type": "teaching_index", "auto_managed": True})
    # Upgrade indexes created before managed markers existed.  Their generated
    # rows are safe to replace; headings and teacher prose remain untouched.
    # Remove legacy/generated rows outside the managed block.  This also
    # retires groups renamed in the ontology (for example LearnerContext)
    # without touching prose or manually-authored links.
    if managed_start not in body:
        known_groups = set(groups) | {"LearnerContext"}
        body = re.sub(
            r"(?m)^- \[[^\n]+\]\(teaching/[^\n]+\) \(`([^`]+)`\)\n?",
            lambda match: "" if match.group(1) in known_groups else match.group(0),
            body,
        )
    body = replace_block(body, managed_start, managed_end, "\n".join(rows))
    root.write_text(make_frontmatter(fm) + "\n" + body.strip() + "\n", encoding="utf-8")


def _migrate_managed_teaching_pages(
    teaching: Path, groups: dict[str, dict[str, object]]
) -> None:
    """Move class pages when the ontology changes a class's group.

    Only taxonomy-owned pages are eligible. Authored content and custom
    frontmatter survive collisions; generated learning summaries are
    regenerated from the event ledger and therefore are not copied twice.
    """
    expected: dict[str, Path] = {}
    labels: dict[str, str] = {}
    for group_name, group in groups.items():
        folder = str(group["folder"])
        group_labels = dict(group.get("labels") or {})
        for class_name in group.get("classes", ()):
            expected[str(class_name)] = teaching / folder / f"{class_name}.md"
            labels[str(class_name)] = str(group_labels.get(class_name, class_name))

    root = teaching.resolve()
    for source in teaching.rglob("*.md"):
        if source.name == "index.md" or source.is_symlink():
            continue
        try:
            source.resolve().relative_to(root)
            raw = source.read_text(encoding="utf-8")
            frontmatter, body = parse_frontmatter(raw)
        except (OSError, UnicodeError, ValueError):
            continue
        if frontmatter.get("auto_managed") is not True or frontmatter.get("type") != "teaching_object":
            continue
        class_name = str(frontmatter.get("ontology_class") or "")
        target = expected.get(class_name)
        if target is None or source.resolve() == target.resolve(strict=False):
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            target.parent.resolve().relative_to(root)
        except ValueError:
            # A manually-created symlink must not redirect taxonomy sync
            # outside this Wiki.
            continue
        if not target.exists():
            os.replace(source, target)
            continue

        target_raw = target.read_text(encoding="utf-8")
        target_fm, target_body = parse_frontmatter(target_raw)
        # Automatic event summaries are reproducible from SQLite. Do not
        # duplicate those generated blocks when merging two managed pages.
        migrated_body = re.sub(
            r"\n?<!-- wiki-auto:learning-summary:start -->.*?<!-- wiki-auto:learning-summary:end -->\n?",
            "\n",
            body,
            flags=re.DOTALL,
        ).strip()
        generated_stub = (
            f"# {labels[class_name]}\n\n"
            f"本页对应 EDU-ONTO v2 的 `{class_name}` 类。\n\n"
            "页面内容可由教师继续补充；系统只维护结构化元数据和事件投影。"
        )
        if migrated_body == generated_stub:
            migrated_body = ""
        migration_marker = f"<!-- ontology-migration:{class_name} -->"
        if migrated_body and migration_marker not in target_body:
            target_body = (
                target_body.rstrip()
                + f"\n\n{migration_marker}\n"
                + "<details><summary>从旧分类目录迁移的补充内容</summary>\n\n"
                + migrated_body
                + "\n\n</details>\n"
            )
        for key, value in frontmatter.items():
            if key not in {"title", "type", "ontology_class", "group", "auto_managed"}:
                target_fm.setdefault(key, value)
        fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(make_frontmatter(target_fm) + "\n" + target_body.strip() + "\n")
            os.replace(temp_name, target)
            source.unlink()
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)


def ensure_dirs(project_id: str = "default"):
    """Create wiki directory structure."""
    dirs = [
        "concepts", "facts", "formulas", "principles", "media",
        # Activity projections are kept separate from authored knowledge pages.
        "learning/activity", "learning/learners", "teaching",
    ]
    wp = wiki_path(project_id)
    for d in dirs:
        (wp / d).mkdir(parents=True, exist_ok=True)
    sources_path(project_id).mkdir(parents=True, exist_ok=True)
    _ensure_teaching_index(wp)

    # Create purpose.md if not exists
    purpose = wp / "purpose.md"
    if not purpose.exists():
        purpose.write_text("""---
title: 教学目标
type: guide
---
# 教学目标

## 课程目标
待定义 - 请编辑此文件来设定教学目标、知识范围和课程大纲。

## 关键问题
待定义

## 学习范围
待定义
""", encoding="utf-8")

    # Create schema.md if not exists
    schema = wp / "schema.md"
    if not schema.exists():
        schema.write_text("""---
title: Wiki 结构规则
type: guide
---
# Wiki 结构规则

## 页面类型
- **concept**: 概念定义，包含定义、解释、示例
- **fact**: 事实，单点为真的具体陈述（常数、具体物质数据、约定阈值）
- **formula**: 数学公式，包含公式、变量说明、推导
- **principle**: 原理/定理，包含陈述、条件、证明/推导
- **teaching_object_group**: TeachingObject 二级分类目录（自动生成）

## 教学应用对象目录
TeachingObject 采用与本体一致的二级分类，目录位于 `teaching/`。目录页由
`ontology_v2.TEACHING_CLASS_GROUPS` 派生，包含学习者身份画像、掌握状态、学习事件、
习题评价、学习规划和资源认知六组。

## 命名规范
- 概念页: `concepts/{概念名}.md`
- 事实页: `facts/{事实名}.md`
- 公式页: `formulas/{公式名}.md`
- 原理页: `principles/{原理名}.md`

## 链接语法
使用 `[[页面路径]]` 语法进行交叉引用。
""", encoding="utf-8")
    else:
        schema_text = schema.read_text(encoding="utf-8")
        if "## 教学应用对象目录" not in schema_text:
            schema.write_text(
                schema_text.rstrip()
                + "\n\n## 教学应用对象目录\n"
                + "TeachingObject 采用与本体一致的二级分类，目录位于 `teaching/`。"
                + "目录页由 `ontology_v2.TEACHING_CLASS_GROUPS` 派生，包含学习者身份画像、"
                + "掌握状态、学习事件、习题评价、学习规划和资源认知六组。\n",
                encoding="utf-8",
            )
        else:
            upgraded = schema_text.replace(
                "包含学习者状态、学习事件、习题评价、\n学习规划和资源认知五组。",
                "包含学习者身份画像、掌握状态、学习事件、\n习题评价、学习规划和资源认知六组。",
            ).replace(
                "包含学习者状态、"
                "学习事件、习题评价、学习规划和资源认知五组。",
                "包含学习者身份画像、掌握状态、"
                "学习事件、习题评价、学习规划和资源认知六组。",
            )
            if upgraded != schema_text:
                schema.write_text(upgraded, encoding="utf-8")

    # Create index.md if not exists
    index_path = wp / "index.md"
    if not index_path.exists():
        index_path.write_text("""---
title: 知识库索引
type: index
updated: ""
---
# 知识库索引

## 概念 (Concepts)

## 事实 (Facts)

## 公式 (Formulas)

## 原理 (Principles)

## 教学应用对象 (TeachingObject)

详见 [[teaching/index]]。
""", encoding="utf-8")
    else:
        raw = index_path.read_text(encoding="utf-8")
        if "## 教学应用对象 (TeachingObject)" not in raw:
            index_path.write_text(
                raw.rstrip() + "\n\n## 教学应用对象 (TeachingObject)\n\n详见 [[teaching/index]]。\n",
                encoding="utf-8",
            )


def parse_frontmatter(content: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from markdown content. Returns (frontmatter_dict, body)."""
    fm_match = re.match(r'^---\n(.*?)\n---\n?(.*)', content, re.DOTALL)
    if fm_match:
        try:
            fm = yaml.safe_load(fm_match.group(1)) or {}
        except yaml.YAMLError:
            fm = {}
        return fm, fm_match.group(2).strip()
    return {}, content


def make_frontmatter(fm: dict) -> str:
    """Generate YAML frontmatter string."""
    return "---\n" + yaml.dump(fm, allow_unicode=True, default_flow_style=False) + "---\n"


def write_wiki_page(relative_path: str, title: str, page_type: str, content: str,
                    sources: list[str] | None = None, tags: list[str] | None = None,
                    prerequisites: list[str] | None = None,
                    difficulty: int | None = None,
                    related: list[str] | None = None,
                    common_misconceptions: list[str] | None = None,
                    worked_example_ref: list[str] | None = None,
                    last_reviewed: str | None = None,
                    *, project_id: str = "default") -> str:
    """Write a wiki page. Returns the absolute path."""
    wp = wiki_path(project_id)
    full_path = wp / relative_path
    full_path.parent.mkdir(parents=True, exist_ok=True)

    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    fm = {
        "title": title,
        "type": page_type,
        "sources": sources or [],
        "tags": tags or [],
        "created": now,
        "updated": now,
    }
    if prerequisites:
        fm["prerequisites"] = prerequisites
    if difficulty is not None:
        fm["difficulty"] = difficulty
    if related:
        fm["related"] = related
    if common_misconceptions:
        fm["common_misconceptions"] = common_misconceptions
    if worked_example_ref:
        fm["worked_example_ref"] = worked_example_ref
    if last_reviewed:
        fm["last_reviewed"] = last_reviewed

    # Check if exists, preserve created date
    if full_path.exists():
        existing_fm, _ = parse_frontmatter(full_path.read_text(encoding="utf-8"))
        if "created" in existing_fm:
            fm["created"] = existing_fm["created"]
        # Preserve last_reviewed if caller didn't supply a new value
        if "last_reviewed" not in fm and "last_reviewed" in existing_fm:
            fm["last_reviewed"] = existing_fm["last_reviewed"]

    text = make_frontmatter(fm) + "\n" + content
    full_path.write_text(text, encoding="utf-8")
    return str(full_path)


def read_wiki_page(relative_path: str, *, project_id: str = "default") -> dict | None:
    """Read a wiki page. Returns full WikiPage dict (incl. v2 structured fields) or None."""
    wp = wiki_path(project_id)
    full_path = wp / relative_path
    if not full_path.exists():
        return None

    raw = full_path.read_text(encoding="utf-8")
    fm, body = parse_frontmatter(raw)

    return {
        "path": relative_path,
        "title": fm.get("title", full_path.stem),
        "page_type": fm.get("type", "unknown"),
        "content": body,
        "sources": fm.get("sources", []),
        "tags": fm.get("tags", []),
        "created": fm.get("created", ""),
        "updated": fm.get("updated", ""),
        "difficulty": fm.get("difficulty"),
        "prerequisites": fm.get("prerequisites", []) or [],
        "related": fm.get("related", []) or [],
        "common_misconceptions": fm.get("common_misconceptions", []) or [],
        "worked_example_ref": fm.get("worked_example_ref", []) or [],
        "last_reviewed": fm.get("last_reviewed", "") or "",
    }


def list_wiki_pages(page_type: str | None = None, *, project_id: str = "default") -> list[dict]:
    """List project-visible Wiki pages, optionally filtered by type.

    Learner snapshots are private operational records, not knowledge pages.
    Excluding them here also keeps them out of search, graph, retrieval, and
    vector-index rebuilds that use this shared listing function.
    """
    wp = wiki_path(project_id)
    pages = []

    for md_file in wp.rglob("*.md"):
        if md_file.name in ("purpose.md", "schema.md", "index.md", "log.md"):
            continue
        rel_path = str(md_file.relative_to(wp))
        fm, body = parse_frontmatter(md_file.read_text(encoding="utf-8"))
        ptype = fm.get("type") or "unknown"
        if ptype == "learner_profile" or is_private_learner_page_path(rel_path):
            continue
        if page_type and ptype != page_type:
            continue
        pages.append({
            "path": rel_path,
            "title": fm.get("title", md_file.stem),
            "type": ptype,
            "summary": body[:200] if body else "",
            "difficulty": fm.get("difficulty"),
            "prerequisites": fm.get("prerequisites", []) or [],
            "common_misconceptions": fm.get("common_misconceptions", []) or [],
            "last_reviewed": fm.get("last_reviewed", "") or "",
        })

    return pages


def delete_wiki_page(relative_path: str, *, project_id: str = "default") -> bool:
    """Delete a wiki page. Returns True if deleted, False if not found."""
    full_path = wiki_path(project_id) / relative_path
    if full_path.exists():
        full_path.unlink()
        # Clean up dead wikilinks in remaining pages
        page_id = relative_path.replace(".md", "")
        _cleanup_dead_links(page_id, project_id=project_id)
        # Remove from vector index
        try:
            from services.vector_store import remove_page
            remove_page(relative_path, project_id=project_id)
        except Exception:
            pass
        return True
    return False


def _cleanup_dead_links(deleted_page_id: str, *, project_id: str = "default"):
    """Remove dead [[wikilinks]] from all wiki pages."""
    wp = wiki_path(project_id)
    link_pattern = re.compile(rf'\[\[{re.escape(deleted_page_id)}(?:\|[^\]]+)?\]\]')

    for md_file in wp.rglob("*.md"):
        content = md_file.read_text(encoding="utf-8")
        new_content = link_pattern.sub("", content)
        if new_content != content:
            md_file.write_text(new_content, encoding="utf-8")


def compute_source_hash(file_path: str) -> str:
    """SHA256 hash of file content for ingest caching."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


def get_ingest_cache(source_path: str, *, project_id: str = "default") -> str | None:
    """Get cached hash for a source file. Returns hash or None."""
    cache_dir = wiki_path(project_id) / ".cache"
    cache_file = cache_dir / (hashlib.md5(source_path.encode()).hexdigest() + ".hash")
    if cache_file.exists():
        return cache_file.read_text().strip()
    return None


def set_ingest_cache(source_path: str, content_hash: str, *, project_id: str = "default"):
    """Cache the hash for a processed source file."""
    cache_dir = wiki_path(project_id) / ".cache"
    cache_dir.mkdir(exist_ok=True)
    cache_file = cache_dir / (hashlib.md5(source_path.encode()).hexdigest() + ".hash")
    cache_file.write_text(content_hash)


def _source_manifest_path(*, project_id: str = "default") -> Path:
    return wiki_path(project_id) / ".source_pages.json"


def read_source_manifest(*, project_id: str = "default") -> dict[str, list[str]]:
    """Read source-to-wiki-page mapping used for exact source reingest cleanup."""
    manifest_path = _source_manifest_path(project_id=project_id)
    if not manifest_path.exists():
        return {}
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        str(source): [str(path) for path in paths if isinstance(path, str)]
        for source, paths in data.items()
        if isinstance(paths, list)
    }


def record_source_pages(source_path: str, page_paths: list[str], *, project_id: str = "default"):
    """Persist the complete set of wiki pages generated for one source file."""
    manifest = read_source_manifest(project_id=project_id)
    manifest[source_path] = sorted(set(page_paths))
    manifest_path = _source_manifest_path(project_id=project_id)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def remove_source_manifest(source_path: str, *, project_id: str = "default"):
    """Remove one source entry from the source-to-pages manifest."""
    manifest = read_source_manifest(project_id=project_id)
    if source_path not in manifest:
        return
    del manifest[source_path]
    manifest_path = _source_manifest_path(project_id=project_id)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def update_index(new_pages: list[dict], *, project_id: str = "default"):
    """Update index.md — merge new/updated pages into existing sections, preserving existing entries."""
    index_path = wiki_path(project_id) / "index.md"
    if not index_path.exists():
        return

    fm, body = parse_frontmatter(index_path.read_text(encoding="utf-8"))
    fm["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Parse existing entries from the body to preserve them
    section_names = _INDEX_SECTION_NAMES

    # Collect existing links per type
    existing: dict[str, set[str]] = {t: set() for t in section_names}
    current_type = None
    for line in body.split("\n"):
        stripped = line.strip()
        if stripped.startswith("## "):
            for t, header in section_names.items():
                if stripped == header:
                    current_type = t
                    break
            else:
                current_type = None
        elif stripped.startswith("- [[") and current_type:
            path = stripped.split("[[", 1)[1].split("]]", 1)[0] if "[[" in stripped else ""
            if path:
                existing[current_type].add(path)

    # Merge in new pages
    new_paths: dict[str, set[str]] = {t: set() for t in section_names}
    for page in new_pages:
        ptype = page.get("type", "unknown")
        if ptype in new_paths:
            link = f"{page['path'].replace('.md', '')}]] - {page.get('title', '')}"
            link = f"- [[{link}"
            new_paths[ptype].add(link)

    # Build sections
    sections = []
    for ptype, header in section_names.items():
        sections.append(header)
        all_entries = existing[ptype] | new_paths[ptype]
        for entry in sorted(all_entries):
            sections.append(entry)
        sections.append("")

    new_body = "\n".join(sections) if sections else body
    text = make_frontmatter(fm) + "\n# 知识库索引\n\n" + new_body
    index_path.write_text(text, encoding="utf-8")


def rebuild_index(*, project_id: str = "default"):
    """Rebuild index.md from current wiki files."""
    pages = list_wiki_pages(project_id=project_id)
    index_path = wiki_path(project_id) / "index.md"
    if not index_path.exists():
        ensure_dirs(project_id=project_id)

    fm = {
        "title": "知识库索引",
        "type": "index",
        "updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    section_names = _INDEX_SECTION_NAMES
    grouped: dict[str, list[dict]] = {t: [] for t in section_names}
    for page in pages:
        if page.get("type") in grouped:
            grouped[page["type"]].append(page)

    sections = []
    for ptype, header in section_names.items():
        sections.append(header)
        for page in sorted(grouped[ptype], key=lambda p: p.get("title", "")):
            link = page["path"].replace(".md", "")
            sections.append(f"- [[{link}]] - {page.get('title', '')}")
        sections.append("")

    text = make_frontmatter(fm) + "\n# 知识库索引\n\n" + "\n".join(sections)
    index_path.write_text(text, encoding="utf-8")


# --- Project management ---

# Only forbid filesystem-unsafe characters: / \ : * ? " < > |
_PROJECT_NAME_RE = re.compile(r'^[^/\\:*?"<>|]+$')


def validate_project_id(project_id: str) -> str:
    """Validate and normalize project_id to prevent path traversal."""
    if not project_id or not _PROJECT_NAME_RE.match(project_id):
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Invalid project ID: {project_id!r}")
    if project_id.startswith("."):
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Invalid project ID: {project_id!r}")
    return project_id


def list_projects() -> list[dict]:
    """List all projects in the projects directory."""
    proj_dir = Path(settings.projects_dir)
    if not proj_dir.exists():
        return []
    projects = []
    for d in sorted(proj_dir.iterdir()):
        if d.is_dir():
            projects.append({"name": d.name, "title": d.name})
    return projects


def create_project(name: str) -> dict:
    """Create a new project with full directory structure."""
    if not _PROJECT_NAME_RE.match(name):
        raise ValueError("Project name contains invalid characters: / \\ : * ? \" < > |")
    # Reserve the project directory before materializing its Wiki.  Previously
    # a second create request with the same name silently called ``ensure_dirs``
    # on the existing directory, making it look as if a new project had
    # inherited the old project's pages, sources, and learning projections.
    # ``exist_ok=False`` also makes the check atomic for concurrent requests.
    projects_root = Path(settings.projects_dir)
    projects_root.mkdir(parents=True, exist_ok=True)
    project_path = projects_root / name
    project_path.mkdir(exist_ok=False)
    try:
        ensure_dirs(project_id=name)
    except Exception:
        # Do not leave a half-created project that would block a retry.  The
        # directory was created by this call, so removing it cannot delete an
        # existing project's data.
        shutil.rmtree(project_path, ignore_errors=True)
        raise
    return {"name": name, "title": name}


def delete_project(name: str) -> bool:
    """Delete a project and all its data. Cannot delete the default project."""
    if name == "default":
        raise ValueError("Cannot delete the default project")
    proj_path = Path(settings.projects_dir) / name
    if proj_path.exists():
        shutil.rmtree(proj_path)
        return True
    return False


# --- Conversation storage ---

def conversations_dir(project_id: str = "default") -> Path:
    validate_project_id(project_id)
    d = Path(settings.projects_dir) / project_id / "conversations"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _validate_conv_id(conv_id: str) -> str:
    """Validate conversation ID to prevent path traversal."""
    if not conv_id or ".." in conv_id or "/" in conv_id or "\\" in conv_id:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Invalid conversation ID")
    return conv_id


def list_conversations(*, project_id: str = "default") -> list[dict]:
    """List all conversations for a project, newest first."""
    cd = conversations_dir(project_id)
    convs = []
    for f in sorted(cd.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            convs.append({
                "id": data.get("id", f.stem),
                "title": data.get("title", "Untitled"),
                "message_count": len(data.get("messages", [])),
                "created": data.get("created", ""),
                "updated": data.get("updated", ""),
            })
        except (json.JSONDecodeError, KeyError):
            continue
    return convs


def get_conversation(conv_id: str, *, project_id: str = "default") -> dict | None:
    """Load a single conversation by ID."""
    _validate_conv_id(conv_id)
    fp = conversations_dir(project_id) / f"{conv_id}.json"
    if not fp.exists():
        return None
    try:
        return json.loads(fp.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def save_conversation(conv: dict, *, project_id: str = "default"):
    """Save (create or update) a conversation."""
    conv_id = conv.get("id", "")
    _validate_conv_id(conv_id)
    conv["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if "created" not in conv:
        conv["created"] = conv["updated"]
    fp = conversations_dir(project_id) / f"{conv['id']}.json"
    fp.write_text(json.dumps(conv, ensure_ascii=False, indent=2), encoding="utf-8")


def delete_conversation(conv_id: str, *, project_id: str = "default") -> bool:
    """Delete a conversation."""
    _validate_conv_id(conv_id)
    fp = conversations_dir(project_id) / f"{conv_id}.json"
    if fp.exists():
        fp.unlink()
        return True
    return False
