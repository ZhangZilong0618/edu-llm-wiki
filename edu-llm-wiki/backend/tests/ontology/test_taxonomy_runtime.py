from __future__ import annotations

import sys

import pytest

from config import settings
from owlready2 import World

from services.ontology_v2 import (
    TEACHING_CLASS_GROUPS,
    build_ontology,
    validate_teaching_taxonomy,
)
from services.wiki_auto_update import _TEACHING_CLASSES, _teaching_page_paths
from storage.wiki_store import _teaching_groups
from storage.wiki_store import ensure_dirs, parse_frontmatter, wiki_path


def test_teaching_helpers_fail_loudly_when_ontology_cannot_load(monkeypatch):
    """A broken ontology must never produce a partial TeachingObject Wiki."""
    monkeypatch.setitem(sys.modules, "services.ontology_v2", None)

    with pytest.raises(ModuleNotFoundError):
        _teaching_groups()
    with pytest.raises(ModuleNotFoundError):
        _teaching_page_paths(("LearningEvents/DialogueRecord",))


def test_every_teaching_class_has_an_event_route_and_directory_projection():
    """Taxonomy additions must be wired to at least one learner event."""
    expected = {
        f"{group}/{class_name}"
        for group, definition in TEACHING_CLASS_GROUPS.items()
        for class_name in definition["classes"]
    }
    routed = {
        class_ref
        for refs in _TEACHING_CLASSES.values()
        for class_ref in refs
    }
    assert routed == expected

    paths = _teaching_page_paths(tuple(sorted(expected)))
    assert paths[0] == "teaching/index.md"
    assert len(paths) == 1 + len(TEACHING_CLASS_GROUPS) + len(expected)
    assert len(paths) == len(set(paths))


def test_startup_materializes_taxonomy_for_every_existing_project(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "projects_dir", str(tmp_path))
    (tmp_path / "legacy" / "wiki").mkdir(parents=True)
    (tmp_path / "second" / "wiki").mkdir(parents=True)

    from main import _materialize_project_wikis

    _materialize_project_wikis()

    expected_groups = {
        "learner-identity",
        "mastery-tracking",
        "learning-events",
        "assessment",
        "learning-planning",
        "learning-support",
    }
    for project_id in ("default", "legacy", "second"):
        teaching = tmp_path / project_id / "wiki" / "teaching"
        assert {path.name for path in teaching.iterdir() if path.is_dir()} == expected_groups
        class_pages = [
            path for path in teaching.rglob("*.md")
            if path.name != "index.md"
        ]
        assert len(class_pages) == 23


def test_taxonomy_sync_removes_legacy_duplicate_lists_and_refreshes_class_metadata(
    monkeypatch, tmp_path
):
    """Upgrading an already-materialized Wiki keeps prose but one list/metadata source."""
    monkeypatch.setattr(settings, "projects_dir", str(tmp_path))
    ensure_dirs(project_id="p")

    group_page = wiki_path("p") / "teaching" / "assessment" / "index.md"
    raw = group_page.read_text(encoding="utf-8")
    # Simulate a page produced by the pre-marker migration: one legacy list
    # plus the managed list already present.
    group_page.write_text(
        raw.replace(
            "<!-- ontology-managed:group-classes:start -->",
            "## 包含对象\n- `Exercise`\n- `ExerciseOption`\n\n"
            "<!-- ontology-managed:group-classes:start -->",
            1,
        ),
        encoding="utf-8",
    )
    class_page = wiki_path("p") / "teaching" / "assessment" / "Exercise.md"
    class_page.write_text(
        "---\n"
        "title: 旧标题\n"
        "type: teaching_object\n"
        "ontology_class: Exercise\n"
        "group: LegacyGroup\n"
        "auto_managed: true\n"
        "---\n\n# 教师补充\n\n正文保留。\n",
        encoding="utf-8",
    )

    ensure_dirs(project_id="p")

    _, body = parse_frontmatter(group_page.read_text(encoding="utf-8"))
    assert body.count("## 包含对象") == 1
    assert body.count("- `Exercise`") == 1
    fm, class_body = parse_frontmatter(class_page.read_text(encoding="utf-8"))
    assert fm["title"] == "习题"
    assert fm["group"] == "AssessmentObjects"
    assert fm["ontology_class"] == "Exercise"
    assert "教师补充" in class_body
    assert "正文保留" in class_body


def test_moved_managed_class_page_merges_authored_content_without_duplicates(
    monkeypatch, tmp_path
):
    """A group change moves the managed page and preserves both authored bodies."""
    monkeypatch.setattr(settings, "projects_dir", str(tmp_path))
    ensure_dirs(project_id="p")
    teaching = wiki_path("p") / "teaching"
    old_page = teaching / "learning-support" / "Exercise.md"
    new_page = teaching / "assessment" / "Exercise.md"
    old_page.write_text(
        "---\n"
        "title: 旧习题页\n"
        "type: teaching_object\n"
        "ontology_class: Exercise\n"
        "group: LearningSupport\n"
        "auto_managed: true\n"
        "custom_note: 保留元数据\n"
        "---\n\n"
        "# 教师补充\n\n旧目录里的详细说明。\n",
        encoding="utf-8",
    )
    new_page.write_text(
        new_page.read_text(encoding="utf-8") + "\n新目录已有说明。\n",
        encoding="utf-8",
    )

    ensure_dirs(project_id="p")
    ensure_dirs(project_id="p")

    assert not old_page.exists()
    fm, body = parse_frontmatter(new_page.read_text(encoding="utf-8"))
    assert fm["group"] == "AssessmentObjects"
    assert fm["custom_note"] == "保留元数据"
    assert "旧目录里的详细说明。" in body
    assert "新目录已有说明。" in body
    assert body.count("ontology-migration:Exercise") == 1


def test_taxonomy_validation_checks_owl_group_inheritance():
    """A mapping-only edit must not hide an OWL hierarchy mismatch."""
    world = World()
    try:
        onto = build_ontology(world=world)
        exercise = onto.Exercise
        assessment = onto.AssessmentObjects
        planning = onto.LearningPlanning
        exercise.is_a.remove(assessment)
        exercise.is_a.append(planning)

        with pytest.raises(ValueError, match="does not match OWL inheritance"):
            validate_teaching_taxonomy(onto)
    finally:
        world.close()
