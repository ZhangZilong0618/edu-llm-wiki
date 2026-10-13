import pytest
import json

from config import settings
from models.chat import ChatRequest
from routes.chat import _agent_mode, _explicit_practice_topic, _practice_topic
from services.graph_store import connect, ensure_schema
from storage.wiki_store import ensure_dirs, write_wiki_page


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("给我一道题", "practice"),
        ("你应该出元素的题目", "practice"),
        ("出关于元素的题目", "practice"),
        ("请问怎么出元素的题目？", "ask"),
        ("怎么出题？", "ask"),
        ("解释一下出题方法", "ask"),
        ("考考我", "practice"),
        ("复习一下到期卡片", "review"),
        ("复习方法怎么设计？", "ask"),
        ("请解释一下练习方法", "ask"),
        ("热电效应是什么？", "ask"),
    ],
)
def test_chat_agent_selects_skill_from_latest_user_intent(message, expected):
    request = ChatRequest(messages=[{"role": "user", "content": message}])
    assert request.mode == "auto"
    assert _agent_mode(request) == expected


def test_practice_topic_uses_explicit_topic_or_recent_dialogue():
    explicit = ChatRequest(messages=[{"role": "user", "content": "你应该出元素的题目"}])
    assert _explicit_practice_topic(explicit.messages[-1].content) == "元素"
    assert _practice_topic(explicit) == "元素"

    contextual = ChatRequest(messages=[
        {"role": "user", "content": "元素是具有相同核电荷数的一类原子的总称。"},
        {"role": "assistant", "content": "元素的化学性质由最外层电子决定。"},
        {"role": "user", "content": "好的，出个题目考察我"},
    ])
    assert _practice_topic(contextual) == (
        "元素是具有相同核电荷数的一类原子的总称。\n元素的化学性质由最外层电子决定。"
    )


def test_chat_practice_inherits_topic_and_returns_structured_card(monkeypatch, tmp_path):
    """A vague follow-up should quiz the active Wiki topic in a card event."""
    project_id = "chat-agent-topic"
    user_id = "learner"
    monkeypatch.setattr(settings, "projects_dir", str(tmp_path))
    ensure_schema(project_id)
    ensure_dirs(project_id)
    # The unrelated page sorts first, which exposed the old first-eight-pages
    # behavior. A topic-aware request must still select the Elements page.
    write_wiki_page(
        "a/polymer.md", "高分子构型", "concept",
        "# 高分子构型\n\n高分子链的立体构型由化学键决定。",
        project_id=project_id,
    )
    write_wiki_page(
        "z/elements.md", "元素", "concept",
        "# 元素\n\n元素是具有相同核电荷数的一类原子的总称。元素的化学性质由最外层电子决定。",
        project_id=project_id,
    )
    captured = {}

    async def fake_generate(req, project_id, existing_count, context, coverage=None):
        from models.tests import TestQuestion

        captured["natural_prompt"] = req.natural_prompt
        captured["context"] = context
        return [TestQuestion(
            id="elements-question", type="multiple_choice",
            prompt="元素的化学性质主要由什么决定？",
            options=["最外层电子", "中子数"], answer="A",
            explanation="最外层电子决定元素的化学性质。",
            related_page="z/elements.md", difficulty="basic",
        )]

    monkeypatch.setattr("routes.tests._generate_questions", fake_generate)
    from main import app
    from fastapi.testclient import TestClient

    client = TestClient(app)
    response = client.post(
        f"/api/chat/stream?project_id={project_id}",
        json={
            "messages": [
                {"role": "user", "content": "元素是什么？"},
                {"role": "assistant", "content": "元素是具有相同核电荷数的一类原子。"},
                {"role": "user", "content": "好的，出个题目考察我"},
            ],
            "conversation_id": "conversation-elements",
            "user_id": user_id,
            "options": {"agent_mode": "auto"},
        },
    )
    assert response.status_code == 200, response.text
    events = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: {")
    ]
    card = next(event for event in events if event["type"] == "practice_question")
    assert card["question"]["related_page"] == "z/elements.md"
    assert "元素的化学性质主要由什么决定" in card["question"]["prompt"]
    assert "# 元素" in captured["context"]
    assert "高分子构型" not in captured["context"]
    assert "元素" in captured["natural_prompt"]


def test_explicit_topic_request_enters_structured_practice_flow(monkeypatch, tmp_path):
    project_id = "chat-agent-explicit-topic"
    monkeypatch.setattr(settings, "projects_dir", str(tmp_path))
    ensure_schema(project_id)
    ensure_dirs(project_id)
    write_wiki_page(
        "concepts/elements.md", "元素", "concept",
        "# 元素\n\n元素是具有相同核电荷数的一类原子的总称。",
        project_id=project_id,
    )

    async def fake_generate(req, project_id, existing_count, context, coverage=None):
        from models.tests import TestQuestion

        assert "元素" in req.natural_prompt
        return [TestQuestion(
            id="explicit-elements", type="short_answer", prompt="什么是元素？",
            answer="同核电荷数原子", explanation="元素按核电荷数定义。",
            related_page="concepts/elements.md", difficulty="basic",
        )]

    monkeypatch.setattr("routes.tests._generate_questions", fake_generate)
    from main import app
    from fastapi.testclient import TestClient

    response = TestClient(app).post(
        f"/api/chat/stream?project_id={project_id}",
        json={
            "messages": [{"role": "user", "content": "你应该出元素的题目"}],
            "conversation_id": "conversation-explicit-elements",
            "user_id": "learner",
            "options": {"agent_mode": "auto"},
        },
    )
    assert response.status_code == 200, response.text
    events = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: {")
    ]
    card = next(event for event in events if event["type"] == "practice_question")
    assert card["question"]["related_page"] == "concepts/elements.md"


def test_chat_sse_question_answer_and_due_review_update_wiki(monkeypatch, tmp_path):
    """Simulate the user journey through the single conversational API."""
    project_id = "chat-agent-e2e"
    user_id = "learner"
    monkeypatch.setattr(settings, "projects_dir", str(tmp_path))
    ensure_schema(project_id)
    ensure_dirs(project_id)
    write_wiki_page(
        "concepts/energy.md",
        "Energy",
        "concept",
        "# Energy\n\nEnergy is the capacity to do work.",
        project_id=project_id,
    )

    async def fake_generate(req, project_id, existing_count, context, coverage=None):
        from models.tests import TestQuestion

        return [TestQuestion(
            id="e2e-question",
            type="multiple_choice",
            prompt="What is energy?",
            options=["Capacity to do work", "A unit of time"],
            answer="A",
            explanation="Energy is the capacity to do work.",
            related_page="concepts/energy.md",
            difficulty="basic",
        )]

    monkeypatch.setattr("routes.tests._generate_questions", fake_generate)
    from main import app
    from fastapi.testclient import TestClient

    client = TestClient(app)

    def ask(text, conversation_id):
        response = client.post(
            f"/api/chat/stream?project_id={project_id}",
            json={
                "messages": [{"role": "user", "content": text}],
                "conversation_id": conversation_id,
                "user_id": user_id,
                "options": {"agent_mode": "auto"},
            },
        )
        assert response.status_code == 200, response.text
        return [
            json.loads(line.removeprefix("data: "))
            for line in response.text.splitlines()
            if line.startswith("data: {")
        ]

    practice_events = ask("给我一道题", "conversation-practice")
    practice = next(event for event in practice_events if event["type"] == "practice_question")
    assert practice["mode"] == "practice"
    assert "answer" not in practice["question"]
    question_id = practice["question"]["question_id"]
    session_id = practice["session_id"]
    attempt_id = "e2e-practice-attempt"

    missing_confidence = client.post(
        f"/api/chat/practice/{session_id}/answer?project_id={project_id}&user_id={user_id}",
        json={"question_id": question_id, "answer": "A"},
    )
    assert missing_confidence.status_code == 422
    invalid_confidence = client.post(
        f"/api/chat/practice/{session_id}/answer?project_id={project_id}&user_id={user_id}",
        json={"question_id": question_id, "answer": "A", "confidence": 0},
    )
    assert invalid_confidence.status_code == 422

    answer = client.post(
        f"/api/chat/practice/{session_id}/answer?project_id={project_id}&user_id={user_id}",
        json={"question_id": question_id, "answer": "A", "confidence": 4, "attempt_id": attempt_id},
    )
    assert answer.status_code == 200, answer.text
    result = answer.json()
    assert result["correct"] is True
    assert result["learning_update"]["bkt"]["p_known"] > 0
    assert result["learning_update"]["sr"]["reps"] == 1

    # A vague follow-up carries only the assessment id from the browser. The
    # chat route restores the question and grading record from server storage,
    # then uses the question as retrieval context and exposes it to the tutor.
    from routes import chat as chat_route

    captured = {}

    async def fake_rag(query, budget, **kwargs):
        captured["query"] = query
        return ("Wiki context", [], "No pages", "Index", "Purpose", "Learner")

    async def fake_stream_chat(*, system_prompt, messages, model=None, abort_signal=None):
        captured["system_prompt"] = system_prompt
        captured["messages"] = messages
        yield "Because B is correct."

    monkeypatch.setattr(chat_route, "_run_rag_pipeline", fake_rag)
    monkeypatch.setattr(chat_route, "stream_chat", fake_stream_chat)
    followup = client.post(
        f"/api/chat/stream?project_id={project_id}",
        json={
            "messages": [
                {"role": "user", "content": "考考我"},
                {"role": "assistant", "content": "开始练习"},
                {"role": "user", "content": "A"},
                {"role": "user", "content": "为什么正确？"},
            ],
            "conversation_id": "conversation-practice",
            "user_id": user_id,
            "options": {
                "agent_mode": "auto",
                "assessment_context_question_id": question_id,
            },
        },
    )
    assert followup.status_code == 200, followup.text
    assert "What is energy?" in captured["query"]
    assert '"correct_answer": "A"' in captured["system_prompt"]
    assert '"learner_answer": "A"' in captured["system_prompt"]
    assert "Energy is the capacity to do work." in captured["system_prompt"]

    retry = client.post(
        f"/api/chat/practice/{session_id}/answer?project_id={project_id}&user_id={user_id}",
        json={"question_id": question_id, "answer": "B", "confidence": 1, "attempt_id": attempt_id},
    )
    assert retry.json() == result
    with connect(project_id) as conn:
        conn.execute("UPDATE sr_schedule SET due_at=0 WHERE user_id=?", (user_id,))

    review_events = ask("复习一下到期卡片", "conversation-review")
    review = next(event for event in review_events if event["type"] == "practice_question")
    assert review["mode"] == "review"
    assert review["question"]["question_id"] == question_id
    review_answer = client.post(
        f"/api/chat/practice/{review['session_id']}/answer?project_id={project_id}&user_id={user_id}",
        json={"question_id": question_id, "answer": "A", "confidence": 5, "attempt_id": "e2e-review-attempt"},
    )
    assert review_answer.status_code == 200, review_answer.text

    with connect(project_id) as conn:
        event_types = {
            row[0] for row in conn.execute(
                "SELECT event_type FROM wiki_update_events WHERE project_id=?", (project_id,)
            )
        }
        attempts = conn.execute(
            "SELECT COUNT(*) FROM attempts_raw WHERE user_id=?", (user_id,)
        ).fetchone()[0]
    assert {"question_issued", "assessment_attempt", "review_completed", "mastery_change"} <= event_types
    assert attempts == 2
    wiki = tmp_path / project_id / "wiki"
    assert "练习反馈" in (wiki / "teaching" / "assessment" / "AssessmentResult.md").read_text(encoding="utf-8")
    assert "复习完成" in (wiki / "learning" / "activity" / next((p.name for p in (wiki / "learning" / "activity").glob("*.md")), "")).read_text(encoding="utf-8")
