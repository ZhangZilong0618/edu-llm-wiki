from pathlib import Path

from config import settings
from services.graph_store import close_all, connect
from services.wiki_auto_update import (
    _safe_user,
    handle_event,
    record_attempt,
    record_dialogue,
    record_learning_event,
    record_question,
    record_review,
    rebuild_projection,
    replay_failed_events,
    strip_projection_blocks_from_knowledge_pages,
)
from services.ontology_v2 import TEACHING_CLASS_GROUPS
from storage.wiki_store import ensure_dirs, write_wiki_page


def test_dialogue_projection_is_idempotent_and_preserves_page_body(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "projects_dir", str(tmp_path))
    close_all()
    ensure_dirs(project_id="p")
    write_wiki_page(
        "concepts/heat.md",
        "热学",
        "concept",
        "# 热学\n\n这是人工维护的正文。",
        project_id="p",
    )

    payload = dict(
        project_id="p",
        user_id="u1",
        query="什么是热学？",
        response="热学研究热现象。",
        conversation_id="c1",
        cited_pages=[{"path": "concepts/heat.md"}],
        event_id="c1:1",
    )
    first = record_dialogue(**payload)
    second = record_dialogue(**payload)
    assert first["status"] == "updated"
    assert second["status"] == "duplicate"

    page = (Path(tmp_path) / "p" / "wiki" / "concepts" / "heat.md").read_text(encoding="utf-8")
    assert "这是人工维护的正文。" in page
    # Knowledge pages stay clean: dialogue projections go to teaching pages.
    assert "对话涉及" not in page
    assert "学习语义快照" not in page
    assert (Path(tmp_path) / "p" / "wiki" / "learning" / "activity").exists()
    # Learner pages are pseudonymous; a caller-provided user id must never be
    # exposed in a shared Wiki filename.
    learner_page = Path(tmp_path) / "p" / "wiki" / "learning" / "learners" / f"{_safe_user('u1', 'p')}.md"
    assert learner_page.exists()
    text = learner_page.read_text(encoding="utf-8")
    assert "什么是热学" not in text
    assert "u1" not in text


def test_attempt_projection_writes_related_page_and_is_bounded(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "projects_dir", str(tmp_path))
    close_all()
    ensure_dirs(project_id="p")
    write_wiki_page(
        "concepts/heat.md",
        "热学",
        "concept",
        "# 热学\n\n正文。",
        project_id="p",
    )
    result = record_attempt(
        "p",
        "u1",
        attempt_id="a1",
        question_id="q1",
        kc_id="kc1",
        related_page="concepts/heat.md",
        evaluation={"score": 0.8},
    )
    duplicate = record_attempt(
        "p",
        "u1",
        attempt_id="a1",
        question_id="q1",
        kc_id="kc1",
        related_page="concepts/heat.md",
        evaluation={"score": 0.8},
    )
    assert result["status"] == "updated"
    assert duplicate["status"] == "duplicate"
    page = (Path(tmp_path) / "p" / "wiki" / "concepts" / "heat.md").read_text(encoding="utf-8")
    # Knowledge pages stay clean; attempts project onto teaching pages only.
    assert "练习反馈" not in page
    assert "学习洞察" not in page
    teaching_events = (
        Path(tmp_path) / "p" / "wiki" / "teaching" / "learning-events" / "ExerciseAttempt.md"
    ).read_text(encoding="utf-8")
    assert teaching_events.count("练习反馈") == 1


def test_learning_insight_aggregates_safe_state_and_counts(monkeypatch, tmp_path):
    """TeachingObject pages expose aggregate state; knowledge pages stay clean."""
    monkeypatch.setattr(settings, "projects_dir", str(tmp_path))
    close_all()
    ensure_dirs(project_id="p")
    write_wiki_page(
        "concepts/heat.md", "热学", "concept", "# 热学\n\n教师维护的正文。", project_id="p",
    )

    record_dialogue(
        "p", "private-user@example.com", query="private question",
        response="private answer", cited_pages=[{"path": "concepts/heat.md"}],
        event_id="insight-dialogue",
    )
    record_attempt(
        "p", "private-user@example.com", attempt_id="insight-attempt",
        question_id="q1", kc_id="kc-heat", related_page="concepts/heat.md",
        evaluation={"score": 0.75},
        learning_update={"bkt": {"p_known": 0.64}, "sr": {"due_at": 1893456000}},
    )

    wiki = Path(tmp_path) / "p" / "wiki"
    page = (wiki / "concepts" / "heat.md").read_text(encoding="utf-8")
    # The knowledge page stays pure authored content.
    assert "教师维护的正文。" in page
    for absent in ("## 学习洞察", "## 学习语义快照", "## 自动学习摘要"):
        assert absent not in page
    assert "private question" not in page
    assert "private answer" not in page
    assert "private-user@example.com" not in page

    # The same aggregates now live on the teaching event pages.
    exercise_attempt = (
        wiki / "teaching" / "learning-events" / "ExerciseAttempt.md"
    ).read_text(encoding="utf-8")
    assert "## 学习洞察" in exercise_attempt
    assert "关联事件: 1 次" in exercise_attempt
    assert "最近知识点: `kc-heat`" in exercise_attempt
    assert "最近得分: 0.750" in exercise_attempt
    assert "BKT 掌握度: 0.640" in exercise_attempt
    assert "SM-2 下次复习:" in exercise_attempt

    assessment = (
        wiki / "teaching" / "assessment" / "AssessmentResult.md"
    ).read_text(encoding="utf-8")
    assert "## 学习洞察" in assessment
    assert "练习结果 1" in assessment
    assert "最近知识点: `kc-heat`" in assessment


def test_projection_redacts_transcript_and_writes_teaching_pages(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "projects_dir", str(tmp_path))
    close_all()
    ensure_dirs(project_id="p")
    write_wiki_page("concepts/heat.md", "热学", "concept", "# 热学\n\n教师正文。", project_id="p")
    record_dialogue(
        "p", "alice@example.com", query="我的手机号 13800000000 是什么？",
        response="这是不应进入 Wiki 的回答。", cited_pages=[{"path": "concepts/heat.md"}],
        event_id="dialogue-1",
    )
    record_attempt(
        "p", "alice@example.com", attempt_id="attempt-1", question_id="q1", kc_id="kc1",
        related_page="concepts/heat.md",
        evaluation={"score": 0.8, "feedback": "包含学生原答案的反馈不应进入共享页。"},
        learning_update={"bkt": {"p_known": 0.82}, "sr": {"due_at": 123.0}},
    )
    wiki = Path(tmp_path) / "p" / "wiki"
    all_text = "\n".join(p.read_text(encoding="utf-8") for p in wiki.rglob("*.md"))
    assert "13800000000" not in all_text
    assert "不应进入 Wiki" not in all_text
    assert "alice@example.com" not in all_text
    assert (wiki / "teaching" / "learning-events" / "DialogueRecord.md").exists()
    assert (wiki / "teaching" / "assessment" / "AssessmentResult.md").exists()


def test_event_routes_cover_every_teaching_page(monkeypatch, tmp_path):
    """Conversation and assessment activity must not leave taxonomy pages stale."""
    monkeypatch.setattr(settings, "projects_dir", str(tmp_path))
    close_all()
    ensure_dirs(project_id="p")

    record_dialogue("p", "u", query="q", response="r", event_id="dialogue-all")
    record_question("p", "u", question_id="question-all", event_id="question-all")
    record_attempt("p", "u", attempt_id="attempt-all", question_id="question-all")
    record_review("p", "u", review_id="review-all")
    handle_event({
        "event_type": "mastery_change",
        "project_id": "p",
        "payload": {"user_id": "u", "event_id": "mastery-all", "kc_id": "kc"},
    })

    wiki = Path(tmp_path) / "p" / "wiki"
    expected_classes = {
        class_name
        for definition in TEACHING_CLASS_GROUPS.values()
        for class_name in definition["classes"]
    }
    class_pages = {
        path.stem: path
        for path in (wiki / "teaching").rglob("*.md")
        if path.name != "index.md"
    }
    assert set(class_pages) == expected_classes
    assert all("自动汇总" in path.read_text(encoding="utf-8") for path in class_pages.values())
    assert "自动汇总" in (wiki / "teaching" / "index.md").read_text(encoding="utf-8")
    assert all(
        "自动汇总" in (wiki / "teaching" / str(definition["folder"]) / "index.md").read_text(encoding="utf-8")
        for definition in TEACHING_CLASS_GROUPS.values()
    )


def test_failed_projection_can_retry(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "projects_dir", str(tmp_path))
    close_all()
    ensure_dirs(project_id="p")
    import services.wiki_auto_update as auto

    original = auto._append_daily_activity
    calls = {"n": 0}

    def fail_once(*args, **kwargs):
        if calls["n"] == 0:
            calls["n"] += 1
            raise OSError("temporary filesystem error")
        return original(*args, **kwargs)

    monkeypatch.setattr(auto, "_append_daily_activity", fail_once)
    first = record_dialogue("p", "u", query="q", response="r", event_id="retry-1")
    second = record_dialogue("p", "u", query="q", response="r", event_id="retry-1")
    assert first["status"] == "failed"
    assert second["status"] == "updated"
    with auto.connect("p") as conn:
        row = conn.execute("SELECT projection_status,attempt_count FROM wiki_update_events").fetchone()
    assert tuple(row) == ("complete", 2)


def test_review_projection_records_review_event_and_score(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "projects_dir", str(tmp_path))
    close_all()
    ensure_dirs(project_id="p")
    write_wiki_page(
        "concepts/heat.md",
        "热学",
        "concept",
        "# 热学\n\n正文。",
        project_id="p",
    )

    result = record_review(
        "p",
        "u1",
        review_id="review-1",
        kc_id="kc1",
        related_page="concepts/heat.md",
        evaluation={"score": 1.0},
        learning_update={
            "bkt": {"p_known": 0.91},
            "sr": {"due_at": 123.0},
        },
    )
    assert result["status"] == "updated"

    with connect("p") as conn:
        row = conn.execute(
            "SELECT event_type,payload_json FROM wiki_update_events WHERE event_type='review_completed'"
        ).fetchone()
    assert row[0] == "review_completed"
    assert '"score": 1.0' in row[1]
    assert '"p_known": 0.91' in row[1]

    learner_pages = list((Path(tmp_path) / "p" / "wiki" / "learning" / "learners").glob("u_*.md"))
    assert len(learner_pages) == 1
    learner_text = learner_pages[0].read_text(encoding="utf-8")
    assert '"event": "review_completed"' in learner_text
    assert '"p_known": 0.91' in learner_text
    assert '"due_at": 123.0' in learner_text


def test_learning_event_projection_is_idempotent_and_updates_teaching_pages(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "projects_dir", str(tmp_path))
    close_all()
    ensure_dirs(project_id="p")
    write_wiki_page(
        "concepts/heat.md",
        "热学",
        "concept",
        "# 热学\n\n正文。",
        project_id="p",
    )

    payload = dict(
        project_id="p",
        user_id="u1",
        event_kind="analysisView",
        related_page="concepts/heat.md",
        kc_id="kc1",
        mode="wiki",
        event_id="learning-event-1",
    )
    first = record_learning_event(**payload)
    second = record_learning_event(**payload)
    assert first["status"] == "updated"
    assert second["status"] == "duplicate"

    wiki = Path(tmp_path) / "p" / "wiki"
    page = (wiki / "concepts" / "heat.md").read_text(encoding="utf-8")
    # Knowledge pages stay clean; the projection lands on teaching pages.
    assert "学习活动（自动汇总）" not in page
    teaching_event = (wiki / "teaching" / "learning-events" / "LearningEvent.md").read_text(encoding="utf-8")
    assert teaching_event.count("学习活动（自动汇总）") == 1
    assert (wiki / "teaching" / "learning-support" / "LearningActivity.md").exists()
    with connect("p") as conn:
        row = conn.execute(
            "SELECT event_type,payload_json FROM wiki_update_events WHERE event_type='learning_event'"
        ).fetchone()
    assert row[0] == "learning_event"
    assert '"event_kind": "analysisView"' in row[1]


def test_malformed_telemetry_is_redacted_without_dropping_event(monkeypatch, tmp_path):
    """Telemetry is untrusted input; a bad score must not lose the event."""
    monkeypatch.setattr(settings, "projects_dir", str(tmp_path))
    close_all()
    ensure_dirs(project_id="p")

    result = record_attempt(
        "p",
        "u1",
        attempt_id="bad-telemetry",
        question_id="q1",
        kc_id="kc1",
        evaluation={"score": "not-a-number"},
        learning_update={"bkt": {"p_known": "nan"}, "sr": {"due_at": None}},
    )
    assert result["status"] == "updated"
    with connect("p") as conn:
        row = conn.execute(
            "SELECT payload_json FROM wiki_update_events WHERE event_type='assessment_attempt'"
        ).fetchone()
    assert '"score": 0.0' in row[0]
    assert '"p_known": 0.0' in row[0]


def test_rebuild_projection_replays_ledger_without_overwriting_authored_body(monkeypatch, tmp_path):
    """Generated files are disposable; the SQLite ledger recreates them."""
    monkeypatch.setattr(settings, "projects_dir", str(tmp_path))
    close_all()
    ensure_dirs(project_id="p")
    write_wiki_page(
        "concepts/heat.md", "热学", "concept",
        "# 热学\n\n教师维护的正文。", project_id="p",
    )
    record_dialogue(
        "p", "u1", query="q", response="private response",
        cited_pages=[{"path": "concepts/heat.md"}], event_id="rebuild-dialogue",
    )
    wiki = Path(tmp_path) / "p" / "wiki"
    activity = list((wiki / "learning" / "activity").glob("*.md"))[0]
    learner = list((wiki / "learning" / "learners").glob("u_*.md"))[0]
    page = wiki / "concepts" / "heat.md"
    # Simulate a lost generated projection while preserving teacher content.
    activity.unlink()
    learner.unlink()
    teaching = wiki / "teaching" / "learning-events" / "DialogueRecord.md"
    rebuilt = rebuild_projection("p")
    assert rebuilt == {"status": "rebuilt", "events": 1, "skipped": 0}
    assert list((wiki / "learning" / "activity").glob("*.md"))
    assert list((wiki / "learning" / "learners").glob("u_*.md"))
    restored = page.read_text(encoding="utf-8")
    assert "教师维护的正文。" in restored
    # The knowledge page rebuilds to pure authored content: no event blocks.
    for absent in ("对话涉及", "## 学习洞察", "学习语义快照", "自动学习摘要"):
        assert absent not in restored
    teaching_restored = teaching.read_text(encoding="utf-8")
    assert "对话涉及" in teaching_restored
    assert "## 学习洞察" in teaching_restored
    assert "关联事件: 1 次" in teaching_restored
    assert "private response" not in "\n".join(p.read_text(encoding="utf-8") for p in wiki.rglob("*.md"))
    # A second rebuild is stable and does not duplicate event markers.
    rebuild_projection("p")
    assert teaching_restored.count("对话涉及") == teaching.read_text(encoding="utf-8").count("对话涉及")


def test_replay_failed_events_uses_redacted_payload_and_closes_ledger(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "projects_dir", str(tmp_path))
    close_all()
    ensure_dirs(project_id="p")
    import services.wiki_auto_update as auto

    original = auto._append_daily_activity
    failed = {"once": True}

    def fail_once(*args, **kwargs):
        if failed["once"]:
            failed["once"] = False
            raise OSError("offline")
        return original(*args, **kwargs)

    monkeypatch.setattr(auto, "_append_daily_activity", fail_once)
    first = record_dialogue(
        "p", "u1", query="sensitive query", response="sensitive answer",
        event_id="replay-dialogue",
    )
    assert first["status"] == "failed"
    result = replay_failed_events("p")
    assert result == {"status": "replayed", "events": 1, "skipped": 0}
    with connect("p") as conn:
        row = conn.execute(
            "SELECT projection_status,attempt_count FROM wiki_update_events"
        ).fetchone()
    assert tuple(row) == ("complete", 2)
    wiki = Path(tmp_path) / "p" / "wiki"
    assert list((wiki / "learning" / "activity").glob("*.md"))
    all_text = "\n".join(p.read_text(encoding="utf-8") for p in wiki.rglob("*.md"))
    assert "sensitive query" not in all_text
    assert "sensitive answer" not in all_text


def test_strip_projection_blocks_from_knowledge_pages(monkeypatch, tmp_path):
    """Legacy event blocks are retired from knowledge pages, teaching untouched."""
    monkeypatch.setattr(settings, "projects_dir", str(tmp_path))
    close_all()
    ensure_dirs(project_id="p")
    legacy = (
        "# 原子\n\n教师正文。\n\n"
        "<!-- wiki-auto:learning-summary:start -->\n## 自动学习摘要\n- 旧事件行\n"
        "<!-- wiki-auto:learning-summary:end -->\n\n"
        "<!-- wiki-auto:semantic-snapshot:start -->\n## 学习语义快照\n- 最近事件: 对话\n"
        "<!-- wiki-auto:semantic-snapshot:end -->\n\n"
        "<!-- wiki-auto:learning-insight:start -->\n## 学习洞察\n- 关联事件: 1 次\n"
        "<!-- wiki-auto:learning-insight:end -->\n"
    )
    write_wiki_page("concepts/atom.md", "原子", "concept", legacy, project_id="p")
    teaching = (
        Path(tmp_path) / "p" / "wiki" / "teaching" / "learning-events" / "LearningEvent.md"
    )
    teaching.write_text(
        teaching.read_text(encoding="utf-8")
        + "\n<!-- wiki-auto:learning-insight:start -->\n## 学习洞察\n- 保留\n"
        "<!-- wiki-auto:learning-insight:end -->\n",
        encoding="utf-8",
    )

    cleaned = strip_projection_blocks_from_knowledge_pages("p")

    assert cleaned == 1
    page = (Path(tmp_path) / "p" / "wiki" / "concepts" / "atom.md").read_text(encoding="utf-8")
    assert "教师正文" in page
    for absent in ("自动学习摘要", "学习语义快照", "学习洞察", "wiki-auto:"):
        assert absent not in page
    teaching_body = teaching.read_text(encoding="utf-8")
    assert "## 学习洞察" in teaching_body
    assert "保留" in teaching_body
    # Idempotent: a second pass finds nothing left to clean.
    assert strip_projection_blocks_from_knowledge_pages("p") == 0
