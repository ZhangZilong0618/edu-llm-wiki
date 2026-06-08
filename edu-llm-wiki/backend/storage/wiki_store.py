"""Wiki store: read/write markdown files with YAML frontmatter."""

import hashlib
import json
import re
import shutil
from datetime import datetime
from pathlib import Path

import yaml

from config import settings


def wiki_path(project_id: str = "default") -> Path:
    return Path(settings.projects_dir) / project_id / "wiki"


def sources_path(project_id: str = "default") -> Path:
    return Path(settings.projects_dir) / project_id / "sources"


def ensure_dirs(project_id: str = "default"):
    """Create wiki directory structure."""
    dirs = [
        "concepts", "formulas", "principles", "exercises", "sources",
        "synthesis", "queries", "media"
    ]
    wp = wiki_path(project_id)
    for d in dirs:
        (wp / d).mkdir(parents=True, exist_ok=True)
    sources_path(project_id).mkdir(parents=True, exist_ok=True)

    # Create purpose.md if not exists
    purpose = wp / "purpose.md"
    if not purpose.exists():
        purpose.write_text("""---
title: 教学目标
type: system
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
type: system
---
# Wiki 结构规则

## 页面类型
- **concept**: 概念定义，包含定义、解释、示例
- **formula**: 数学公式，包含公式、变量说明、推导
- **principle**: 原理/定理，包含陈述、条件、证明/推导
- **exercise**: 习题/例题，包含题目、解答、知识点
- **source**: 来源摘要，对原始文档的总结
- **synthesis**: 综合分析，跨来源的对比和综合
- **query**: 问答记录，保存的有价值问答

## 命名规范
- 概念页: `concepts/{概念名}.md`
- 公式页: `formulas/{公式名}.md`
- 习题页: `exercises/{题目标题}.md`

## 链接语法
使用 `[[页面路径]]` 语法进行交叉引用。
""", encoding="utf-8")

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

## 公式 (Formulas)

## 原理 (Principles)

## 习题 (Exercises)

## 来源 (Sources)

## 综合分析 (Synthesis)
""", encoding="utf-8")


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

    # Check if exists, preserve created date
    if full_path.exists():
        existing_fm, _ = parse_frontmatter(full_path.read_text(encoding="utf-8"))
        if "created" in existing_fm:
            fm["created"] = existing_fm["created"]

    text = make_frontmatter(fm) + "\n" + content
    full_path.write_text(text, encoding="utf-8")
    return str(full_path)


def read_wiki_page(relative_path: str, *, project_id: str = "default") -> dict | None:
    """Read a wiki page. Returns {path, title, type, content, sources, tags, created, updated} or None."""
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
    }


def list_wiki_pages(page_type: str | None = None, *, project_id: str = "default") -> list[dict]:
    """List all wiki pages, optionally filtered by type."""
    wp = wiki_path(project_id)
    pages = []

    for md_file in wp.rglob("*.md"):
        if md_file.name in ("purpose.md", "schema.md", "index.md", "log.md"):
            continue
        rel_path = str(md_file.relative_to(wp))
        fm, body = parse_frontmatter(md_file.read_text(encoding="utf-8"))
        ptype = fm.get("type", "unknown")
        if page_type and ptype != page_type:
            continue
        pages.append({
            "path": rel_path,
            "title": fm.get("title", md_file.stem),
            "type": ptype,
            "summary": body[:200] if body else "",
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


def update_index(new_pages: list[dict], *, project_id: str = "default"):
    """Update index.md with new/modified pages."""
    index_path = wiki_path(project_id) / "index.md"
    if not index_path.exists():
        return

    fm, body = parse_frontmatter(index_path.read_text(encoding="utf-8"))
    fm["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Group pages by type
    grouped: dict[str, list[str]] = {}
    for page in new_pages:
        ptype = page.get("type", "unknown")
        if ptype not in grouped:
            grouped[ptype] = []
        grouped[ptype].append(f"- [[{page['path'].replace('.md', '')}]] - {page.get('title', '')}")

    # Rebuild index sections
    section_names = {
        "concept": "## 概念 (Concepts)",
        "formula": "## 公式 (Formulas)",
        "principle": "## 原理 (Principles)",
        "exercise": "## 习题 (Exercises)",
        "source": "## 来源 (Sources)",
        "synthesis": "## 综合分析 (Synthesis)",
        "query": "## 问答记录 (Queries)",
    }

    sections = []
    for ptype, name in section_names.items():
        sections.append(name)
        if ptype in grouped:
            sections.extend(grouped[ptype])
        sections.append("")

    new_body = "\n".join(sections) if sections else body
    text = make_frontmatter(fm) + "\n# 知识库索引\n\n" + new_body
    index_path.write_text(text, encoding="utf-8")


# --- Project management ---

# Only forbid filesystem-unsafe characters: / \ : * ? " < > |
_PROJECT_NAME_RE = re.compile(r'^[^/\\:*?"<>|]+$')


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
    ensure_dirs(project_id=name)
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
    d = Path(settings.projects_dir) / project_id / "conversations"
    d.mkdir(parents=True, exist_ok=True)
    return d


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
    fp = conversations_dir(project_id) / f"{conv_id}.json"
    if not fp.exists():
        return None
    return json.loads(fp.read_text(encoding="utf-8"))


def save_conversation(conv: dict, *, project_id: str = "default"):
    """Save (create or update) a conversation."""
    conv["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if "created" not in conv:
        conv["created"] = conv["updated"]
    fp = conversations_dir(project_id) / f"{conv['id']}.json"
    fp.write_text(json.dumps(conv, ensure_ascii=False, indent=2), encoding="utf-8")


def delete_conversation(conv_id: str, *, project_id: str = "default") -> bool:
    """Delete a conversation."""
    fp = conversations_dir(project_id) / f"{conv_id}.json"
    if fp.exists():
        fp.unlink()
        return True
    return False
