from __future__ import annotations

from config import settings
from services.ontology.abox import ABox
from services.ontology.derive import generate_tree
from storage.wiki_store import wiki_path


def test_tree_materializes_teaching_taxonomy(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "projects_dir", str(tmp_path))
    box = ABox.scratch("tree_project")
    try:
        first = generate_tree(box)
        second = generate_tree(box)

        teaching = next(section for section in first["sections"] if section["id"] == "teaching")
        # TeachingObject categories are the sole home for business classes;
        # legacy parallel events/assessment/planning roots must not reappear.
        assert [section["id"] for section in first["sections"]] == ["knowledge", "teaching"]
        assert [group["id"] for group in teaching["children"]] == [
            "LearnerIdentity", "MasteryTracking", "LearningEvents", "AssessmentObjects",
            "LearningPlanning", "LearningSupport",
        ]
        class_pages = [child for group in teaching["children"] for child in group["children"]]
        assert len(class_pages) == 23
        assert all(child["description"] for child in class_pages)
        assert all((wiki_path(box.project_id) / child["path"]).exists() for child in class_pages)
        assert first["sections"] == second["sections"]

        # A teacher-owned edit survives the next directory projection.
        edited = wiki_path(box.project_id) / class_pages[0]["path"]
        edited.write_text(edited.read_text(encoding="utf-8") + "\n人工补充\n", encoding="utf-8")
        generate_tree(box)
        assert "人工补充" in edited.read_text(encoding="utf-8")

        # Every business class is represented once and only once in the tree.
        classes = [child["class"] for child in class_pages]
        assert len(classes) == len(set(classes))

        # A taxonomy change updates only the managed block; teacher prose stays.
        group_page = wiki_path(box.project_id) / "teaching" / "learner-identity" / "index.md"
        group_page.write_text(group_page.read_text(encoding="utf-8") + "\n教师说明\n", encoding="utf-8")
        generate_tree(box)
        assert "教师说明" in group_page.read_text(encoding="utf-8")
    finally:
        box.world.close()
