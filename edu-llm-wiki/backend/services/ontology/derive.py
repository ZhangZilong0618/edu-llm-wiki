"""Derive a stable directory view from the EDU-ONTO ABox and Wiki pages.

The ontology remains the source of truth for types and learner state.  This
module only shapes that data for the UI/API; it never writes assertions back
to the ABox and therefore is safe to call repeatedly.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from services.ontology.edu_onto import PAGE_TEMPLATES
from storage.wiki_store import ensure_dirs, list_wiki_pages


_KNOWLEDGE_TYPES = ("Fact", "Concept", "Formula", "Principle", "Procedure")
_LEARNING_BUCKETS = (
    ("mastered", "已掌握"),
    ("ready", "已就绪"),
    ("transfer_candidates", "迁移候选"),
    ("at_risk", "风险预警"),
)


def _page_type_for_template(page_type: str) -> str:
    for template, (atom_class, _label) in PAGE_TEMPLATES.items():
        if page_type == template or page_type == atom_class.lower():
            return template
    return page_type or "unknown"


def _knowledge_children(pages: list[dict]) -> list[dict]:
    grouped: defaultdict[str, list[dict]] = defaultdict(list)
    for page in pages:
        page_type = str(page.get("type") or "unknown")
        if page_type in {
            "guide", "index", "teaching_index", "teaching_object_group",
            "teaching_object", "learning_event_log", "learner_profile",
        }:
            continue
        grouped[page_type].append({
            "id": page["path"],
            "title": page.get("title") or page["path"],
            "path": page["path"],
            "type": _page_type_for_template(page_type),
            "summary": page.get("summary", ""),
            "difficulty": page.get("difficulty"),
        })
    return [
        {"id": key, "title": key, "type": key, "children": sorted(value, key=lambda x: x["title"])}
        for key, value in sorted(grouped.items())
    ]


def _teaching_children() -> list[dict]:
    # TeachingObject's hierarchy, Wiki folders and API directory all follow
    # the same ontology taxonomy.  Do not silently return an empty tree when
    # the taxonomy module fails to load: that would make the UI look valid
    # while hiding every teaching object.
    from services.ontology_v2 import TEACHING_CLASS_GROUPS, TEACHING_CLASS_LABELS

    return [
        {
            "id": group_name,
            "title": str(group["zh"]),
            "folder": str(group["folder"]),
            "type": group_name,
            "classes": list(group.get("classes") or ()),
            "children": [
                {
                    "id": f"teaching/{group['folder']}/{name}.md",
                    "title": TEACHING_CLASS_LABELS.get(name, (name, ""))[0],
                    "class": name,
                    "description": TEACHING_CLASS_LABELS.get(name, (name, ""))[1],
                    "type": "TeachingObject",
                    "path": f"teaching/{group['folder']}/{name}.md",
                }
                for name in group.get("classes") or ()
            ],
        }
        for group_name, group in TEACHING_CLASS_GROUPS.items()
    ]


def _learner_sections(learner_view: Any | None) -> list[dict]:
    if learner_view is None:
        return []
    values = learner_view.to_dict() if hasattr(learner_view, "to_dict") else dict(learner_view)
    return [
        {
            "id": key,
            "title": label,
            "type": "learner_state",
            "children": [
                {"id": item, "title": item, "type": "KnowledgeAtom"}
                for item in values.get(key, [])
            ],
        }
        for key, label in _LEARNING_BUCKETS
    ]


def generate_tree(abox, *, learner: str | None = None) -> dict:
    """Return the ontology directory and optional learner-state view.

    Teaching business classes appear only under the six taxonomy groups.  In
    particular, event, assessment and planning classes are not duplicated as
    parallel top-level sections.
    """
    ensure_dirs(project_id=abox.project_id)
    pages = list_wiki_pages(project_id=abox.project_id)
    sections = [
        {
            "id": "knowledge",
            "title": "知识原子",
            "type": "knowledge",
            "children": _knowledge_children(pages),
        },
        {
            "id": "teaching",
            "title": "教学应用对象",
            "type": "TeachingObject",
            "children": _teaching_children(),
        },
    ]
    if learner:
        from services.ontology.reasoning import build_learner_view

        sections.append({
            "id": "learner-state",
            "title": f"学习者状态 · {learner}",
            "type": "learner_state",
            "children": _learner_sections(build_learner_view(abox, learner)),
        })
    return {
        "project_id": abox.project_id,
        "learner": learner,
        "sections": sections,
        "page_count": len(pages),
        "ontology_version": "2.0",
    }


__all__ = ["generate_tree"]
