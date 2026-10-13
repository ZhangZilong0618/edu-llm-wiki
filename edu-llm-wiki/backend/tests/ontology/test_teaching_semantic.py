"""Tests for the system-maintained TeachingObject class pages.

Covers the closed loop: taxonomy sync renders ontology semantics + operational
statistics; learning events re-render the routed class pages; plan writes
re-render the LearningPlanning pages; legacy "teacher-supplement" stubs are
retired while authored content survives.
"""

from config import settings
from storage.wiki_store import ensure_dirs, parse_frontmatter, wiki_path

LEGACY_STUB = "页面内容可由教师继续补充；系统只维护结构化元数据和事件投影。"


def _class_page(project_id: str, folder: str, class_name: str):
    return wiki_path(project_id) / "teaching" / folder / f"{class_name}.md"


def test_class_pages_are_system_maintained(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "projects_dir", str(tmp_path))
    ensure_dirs(project_id="p")

    page = _class_page("p", "learning-events", "LearningEvent")
    fm, body = parse_frontmatter(page.read_text(encoding="utf-8"))
    assert fm["type"] == "teaching_object"
    assert "由系统自动维护" in body
    assert LEGACY_STUB not in body

    # Ontology semantics block: label, taxonomy position, description.
    start = body.index("<!-- wiki-auto:ontology-semantic:start -->")
    end = body.index("<!-- wiki-auto:ontology-semantic:end -->")
    semantic = body[start:end]
    assert "## 本体定义 · 学习事件" in semantic
    assert "`LearningEvent`" in semantic
    assert "分类: 学习事件(`LearningEvents`)" in semantic
    # With no recorded events the operational-data section is omitted
    # entirely rather than rendered empty.
    assert "## 运行数据" not in semantic
    assert "系统自动渲染与刷新" in semantic


def test_legacy_stub_retired_authored_body_preserved(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "projects_dir", str(tmp_path))
    page = _class_page("p", "assessment", "Exercise")
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(
        "---\n"
        "title: 旧标题\n"
        "type: teaching_object\n"
        "ontology_class: Exercise\n"
        "group: LegacyGroup\n"
        "auto_managed: true\n"
        "---\n\n"
        f"# 习题\n\n本页对应 EDU-ONTO v2 的 `Exercise` 类。\n\n{LEGACY_STUB}\n\n"
        "教学重点:先讲选项结构。\n",
        encoding="utf-8",
    )

    ensure_dirs(project_id="p")
    _, body = parse_frontmatter(page.read_text(encoding="utf-8"))
    assert LEGACY_STUB not in body
    # Authored content survives; only the stub sentence is retired.
    assert "教学重点:先讲选项结构。" in body
    assert "<!-- wiki-auto:ontology-semantic:start -->" in body


def test_event_refreshes_routed_class_statistics(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "projects_dir", str(tmp_path))
    from services.graph_store import ensure_schema

    ensure_schema("p")
    ensure_dirs(project_id="p")

    from services.wiki_auto_update import record_dialogue, record_question

    record_dialogue("p", "u1", query="q", response="r", conversation_id="c1")
    page = _class_page("p", "learning-events", "LearningEvent")
    _, body = parse_frontmatter(page.read_text(encoding="utf-8"))
    assert "学习事件总量: **1**(对话完成 1)" in body

    record_question("p", "u1", question_id="q1", kc_id=None, related_page=None)
    _, body = parse_frontmatter(page.read_text(encoding="utf-8"))
    assert "学习事件总量: **2**" in body

    # Assessment statistics refresh on the Exercise class page once a real
    # server-owned card exists (record_question only projects the event).
    from services.graph_store import connect

    with connect("p") as conn:
        conn.execute(
            """INSERT INTO agent_questions(
                project_id,user_id,question_id,session_id,kc_id,prompt,question_type,
                options_json,answer_json,explanation,related_page,concepts_json,
                difficulty,hints_json,mode,created_at
            ) VALUES('p','u1','q1','s1','kc:a','题干','multiple_choice',
                '[]','"A"','','a.md','[]','mixed','[]','practice',0)"""
        )
    record_question("p", "u1", question_id="q2", kc_id="kc:a", related_page="a.md")
    exercise_page = _class_page("p", "assessment", "Exercise")
    _, exercise_body = parse_frontmatter(exercise_page.read_text(encoding="utf-8"))
    assert "服务端题卡: **1** 张" in exercise_body


def test_plan_write_refreshes_planning_pages(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "projects_dir", str(tmp_path))
    from services.graph_store import ensure_schema

    ensure_schema("p")
    ensure_dirs(project_id="p")

    import services.learning.plan_store as plan_store

    nodes = [
        {"id": "kc:a", "label": "金属键", "node_type": "concept", "metadata": {"path": "a.md"}},
        {"id": "kc:b", "label": "晶体结构", "node_type": "concept", "metadata": {"path": "b.md"}},
    ]
    edges = [{"source": "kc:a", "target": "kc:b", "edge_type": "prerequisite", "weight": 0.9}]
    for target in ("services.learning.path", "services.learning.plan_store"):
        monkeypatch.setattr(f"{target}.get_nodes", lambda project_id: nodes)
        monkeypatch.setattr(f"{target}.get_edges", lambda project_id: edges)

    plan_store.write_plan("p", "u1", reason="初始规划", overlay=[])

    page = _class_page("p", "learning-planning", "LearningPath")
    _, body = parse_frontmatter(page.read_text(encoding="utf-8"))
    assert "学习者规划: **1** 份" in body
    assert "2 个知识节点 / 1 条先修关系" in body


def test_refresh_preserves_event_projection_blocks(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "projects_dir", str(tmp_path))
    ensure_dirs(project_id="p")

    from services.teaching_semantic import refresh_class_page

    page = _class_page("p", "learning-events", "LearningEvent")
    raw = page.read_text(encoding="utf-8")
    _, body = parse_frontmatter(raw)
    marker = (
        "<!-- wiki-auto:learning-summary:start -->\n- 旧事件行\n"
        "<!-- wiki-auto:learning-summary:end -->"
    )
    # Insert the event-projection block outside the semantic block so the
    # refresh replaces only its own managed region.
    page.write_text(
        raw.replace(
            "<!-- wiki-auto:ontology-semantic:end -->",
            "<!-- wiki-auto:ontology-semantic:end -->\n\n" + marker,
        ),
        encoding="utf-8",
    )

    assert refresh_class_page("p", "LearningEvent") is True
    _, body = parse_frontmatter(page.read_text(encoding="utf-8"))
    assert "<!-- wiki-auto:learning-summary:start -->" in body
    assert "旧事件行" in body
    assert body.count("<!-- wiki-auto:ontology-semantic:start -->") == 1
