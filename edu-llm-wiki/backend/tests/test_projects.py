"""Project lifecycle and isolation tests."""

import pytest


def test_create_project_rejects_existing_name_and_keeps_projects_isolated(monkeypatch, tmp_path):
    from config import settings
    from storage.wiki_store import create_project, wiki_path

    monkeypatch.setattr(settings, "projects_dir", str(tmp_path / "projects"))

    create_project("source")
    authored = wiki_path("source") / "teaching" / "assessment" / "Exercise.md"
    authored.write_text(
        authored.read_text(encoding="utf-8") + "\n教师在 source 项目补充的内容\n",
        encoding="utf-8",
    )

    with pytest.raises(FileExistsError):
        create_project("source")

    create_project("fresh")
    fresh_page = wiki_path("fresh") / "teaching" / "assessment" / "Exercise.md"
    assert fresh_page.exists()
    assert "教师在 source 项目补充的内容" not in fresh_page.read_text(encoding="utf-8")
