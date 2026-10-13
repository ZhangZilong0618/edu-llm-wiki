"""Tests for the persisted learning plan (snapshot, diff, overlay adjustments)."""

import asyncio
import json
from contextlib import asynccontextmanager

import services.learning.plan_store as plan_store
import services.mcp_tools as mcp_tools
import services.react_agent as react_agent

NODES = [
    {"id": "kc:a", "label": "金属键", "node_type": "concept", "metadata": {"path": "concepts/金属键.md"}},
    {"id": "kc:b", "label": "晶体结构", "node_type": "concept", "metadata": {"path": "concepts/晶体结构.md"}},
    {"id": "kc:c", "label": "空间点阵", "node_type": "concept", "metadata": {"path": "concepts/空间点阵.md"}},
    {"id": "kc:d", "label": "布拉维格子", "node_type": "concept", "metadata": {"path": "concepts/布拉维格子.md"}},
    {"id": "kc:e", "label": "相图", "node_type": "concept", "metadata": {"path": "concepts/相图.md"}},
]
EDGES = [
    {"source": "kc:a", "target": "kc:c", "edge_type": "prerequisite", "weight": 0.9},
    {"source": "kc:c", "target": "kc:d", "edge_type": "prerequisite", "weight": 0.9},
    {"source": "kc:b", "target": "kc:e", "edge_type": "prerequisite", "weight": 0.9},
]
BKT_ROWS = [
    {"kc_id": "kc:a", "p_known": 0.9},
    {"kc_id": "kc:b", "p_known": 0.5},
]


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _FakeConn:
    def __init__(self, bkt_rows):
        self._bkt_rows = bkt_rows

    def execute(self, sql, params=()):
        if "bkt_params" in sql:
            return _FakeCursor(self._bkt_rows)
        return _FakeCursor([])


def _patch_graph(monkeypatch, tmp_path, *, nodes=None, edges=None, bkt_rows=None):
    """Patch graph reads (all import bindings) and the wiki root."""
    nodes = NODES if nodes is None else nodes
    edges = EDGES if edges is None else edges
    bkt_rows = BKT_ROWS if bkt_rows is None else bkt_rows
    for target in (
        "services.graph_store",
        "services.learning.path",
        "services.learning.plan_store",
    ):
        monkeypatch.setattr(f"{target}.get_nodes", lambda project_id: nodes)
        monkeypatch.setattr(f"{target}.get_edges", lambda project_id: edges)

    from contextlib import contextmanager

    @contextmanager
    def fake_connect(project_id):
        yield _FakeConn(bkt_rows)

    monkeypatch.setattr("services.graph_store.connect", fake_connect)
    monkeypatch.setattr("services.learning.plan_store.wiki_path", lambda project_id="default": tmp_path)
    return tmp_path


@asynccontextmanager
async def _mcp_session(server):
    """Version-agnostic in-process MCP client session for tests."""
    if react_agent._MCP_TRANSPORT_V2:
        from mcp import ClientSession
        from mcp.client._memory import InMemoryTransport

        async with InMemoryTransport(server) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            yield session
    else:
        from mcp.shared.memory import create_connected_server_and_client_session

        async with create_connected_server_and_client_session(server) as session:
            yield session


def test_write_and_read_roundtrip(monkeypatch, tmp_path):
    _patch_graph(monkeypatch, tmp_path)
    result = plan_store.write_plan(
        "default", "learner-1", reason="初始规划", overlay=[],
    )

    path = tmp_path / "learning" / "plan"
    assert list(path.glob("u_*.md")), "plan file must be created under learning/plan/"

    plan = result["plan"]
    assert [lv["level"] for lv in plan["levels"]] == [1, 2, 3]
    assert {n["id"] for n in plan["levels"][0]["nodes"]} == {"kc:a", "kc:b"}

    stored = plan_store.read_plan("default", "learner-1")
    fm, markdown = stored["frontmatter"], stored["markdown"]
    assert fm["type"] == "learning_plan"
    assert fm["reason"] == "初始规划"
    assert len(fm["node_ids"]) == 5
    assert fm["graph_fingerprint"]["prereq_edge_count"] == 3
    assert fm["mastery_fingerprint"]["mastered_count"] == 1
    assert "第 1 层" in markdown
    assert "金属键" in markdown and "空间点阵" in markdown
    assert "✅" in markdown and "⏳" in markdown  # mastered and upcoming marks


def test_plan_diff_reports_changes_and_stability(monkeypatch, tmp_path):
    _patch_graph(monkeypatch, tmp_path)
    plan_store.write_plan("default", "u", reason="初始规划", overlay=[])

    stable = plan_store.plan_diff("default", "u")
    assert stable["exists"] is True
    assert stable["graph_changed"] is False
    assert stable["newly_mastered"] == []
    assert "无实质变化" in stable["summary"]

    # Grow the graph and let the learner master 晶体结构.
    extra_node = {"id": "kc:f", "label": "固溶体", "node_type": "concept", "metadata": {"path": "concepts/固溶体.md"}}
    _patch_graph(
        monkeypatch, tmp_path,
        nodes=NODES + [extra_node],
        edges=EDGES + [{"source": "kc:e", "target": "kc:f", "edge_type": "prerequisite", "weight": 0.8}],
        bkt_rows=BKT_ROWS + [{"kc_id": "kc:b", "p_known": 0.9}],
    )
    changed = plan_store.plan_diff("default", "u")
    assert changed["graph_changed"] is True
    assert changed["new_nodes"] == ["固溶体"]
    assert changed["newly_mastered"] == ["晶体结构"]
    assert "新增 1 个知识页" in changed["summary"]


def test_adjustments_are_replayed_and_persisted(monkeypatch, tmp_path):
    _patch_graph(monkeypatch, tmp_path)
    plan_store.write_plan("default", "u", reason="初始规划", overlay=[])

    result = plan_store.apply_adjustments(
        "default", "u",
        [
            {"op": "move_to_front", "node": "空间点阵"},
            {"op": "remove", "node": "相图", "note": "暂时不学"},
            {"op": "annotate", "node": "布拉维格子", "note": "重点掌握"},
        ],
        note="把空间点阵提前,先不学相图",
    )

    report = result["report"]
    assert len(report["applied"]) == 3
    plan = result["plan"]
    level1 = plan["levels"][0]
    assert level1["nodes"][0]["id"] == "kc:c"  # 空间点阵 moved to the front
    assert "相图" not in {n["label"] for lv in plan["levels"] for n in lv["nodes"]}
    bravais = next(n for lv in plan["levels"] for n in lv["nodes"] if n["id"] == "kc:d")
    assert bravais["user_notes"] == ["重点掌握"]
    assert plan["removed_by_user"] == [{"label": "相图", "note": "暂时不学"}]
    assert "已按用户要求移除" in result["markdown"]

    # The overlay is stored and replays on re-derivation.
    stored = plan_store.read_plan("default", "u")
    overlay = json.loads(stored["frontmatter"]["overlay_json"])
    assert stored["frontmatter"]["adjustment_count"] == 3
    assert overlay[0] == {"op": "move_to_front", "node": "空间点阵", "at": overlay[0]["at"],
                          "request": "把空间点阵提前,先不学相图"}

    # A later adjustment appends to the overlay (audit grows).
    result2 = plan_store.apply_adjustments(
        "default", "u", [{"op": "annotate", "node": "金属键", "note": "复习"}], note="",
    )
    assert len(result2["report"]["applied"]) == 1
    stored2 = plan_store.read_plan("default", "u")
    assert stored2["frontmatter"]["adjustment_count"] == 4


def test_move_before_prerequisite_violation_is_rejected(monkeypatch, tmp_path):
    _patch_graph(monkeypatch, tmp_path)
    plan_store.write_plan("default", "u", reason="初始规划", overlay=[])

    # 金属键 is a prerequisite of 空间点阵; moving 空间点阵 before it must be
    # rejected rather than silently corrupting the topology order.
    result = plan_store.apply_adjustments(
        "default", "u",
        [{"op": "move_before", "node": "空间点阵", "before": "金属键"}],
        note="试试违规移动",
    )
    assert result["report"]["rejected"], "prerequisite-violating move must be rejected"
    plan = result["plan"]
    lattice = next(n for lv in plan["levels"] for n in lv["nodes"] if n["id"] == "kc:c")
    assert lattice["level"] == 2, "node must stay in its topological level"


def test_rebuild_resets_overlay(monkeypatch, tmp_path):
    _patch_graph(monkeypatch, tmp_path)
    plan_store.write_plan("default", "u", reason="初始规划", overlay=[])
    plan_store.apply_adjustments(
        "default", "u", [{"op": "remove", "node": "相图", "note": "不学"}], note="",
    )

    rebuilt = plan_store.write_plan(
        "default", "u", reason="图谱更新后重规划", overlay=[],
    )
    assert rebuilt["plan"]["removed_by_user"] == []
    stored = plan_store.read_plan("default", "u")
    assert json.loads(stored["frontmatter"]["overlay_json"]) == []
    assert stored["frontmatter"]["adjustment_count"] == 0
    assert "已按用户要求移除" not in stored["markdown"]


def test_remove_short_label_removes_whole_topic_cluster(monkeypatch, tmp_path):
    # "空间" as a short label must remove the whole cluster (空间点阵) rather
    # than being skipped for having no exact node named 空间.
    _patch_graph(monkeypatch, tmp_path)
    plan_store.write_plan("default", "u", reason="初始规划", overlay=[])

    result = plan_store.apply_adjustments(
        "default", "u", [{"op": "remove", "node": "空间", "note": "先不学"}], note="",
    )
    assert any("空间点阵" in item for item in result["report"]["applied"])
    labels = {n["label"] for lv in result["plan"]["levels"] for n in lv["nodes"]}
    assert "空间点阵" not in labels

    # Ambiguous move stays safe: with two nodes containing "空间" the cluster
    # label cannot be moved as one node.
    extra = {"id": "kc:g", "label": "空间群", "node_type": "concept",
             "metadata": {"path": "concepts/空间群.md"}}
    _patch_graph(monkeypatch, tmp_path, nodes=NODES + [extra])
    result2 = plan_store.apply_adjustments(
        "default", "u", [{"op": "move_to_front", "node": "空间"}], note="",
    )
    assert result2["report"]["rejected"], "cluster label move must be rejected"


def test_mcp_plan_tools_round_trip(monkeypatch, tmp_path):
    _patch_graph(monkeypatch, tmp_path)
    evidence = mcp_tools.EvidenceRegistry()
    server = mcp_tools.build_wiki_tool_server(
        project_id="default", user_id="u", evidence=evidence,
    )

    async def run():
        async with _mcp_session(server) as session:
            listed = await session.list_tools()
            names = {tool.name for tool in listed.tools}
            assert {"get_learning_plan", "rebuild_learning_plan", "adjust_learning_plan"} <= names

            missing = await session.call_tool("get_learning_plan", {})
            assert "No learning plan exists" in getattr(missing.content[0], "text", "")

            rebuilt = await session.call_tool("rebuild_learning_plan", {"reason": "测试"})
            assert "第 1 层" in getattr(rebuilt.content[0], "text", "")
            assert not getattr(rebuilt, "is_error", getattr(rebuilt, "isError", False))

            stored = await session.call_tool("get_learning_plan", {})
            stored_text = getattr(stored.content[0], "text", "")
            assert "金属键" in stored_text
            assert "Snapshot comparison" in stored_text

            adjusted = await session.call_tool("adjust_learning_plan", {
                "operations": json.dumps([{"op": "annotate", "node": "相图", "note": "后面再说"}]),
                "note": "标注一下",
            })
            adjusted_text = getattr(adjusted.content[0], "text", "")
            assert "Adjustment result" in adjusted_text
            assert "💬 后面再说" in adjusted_text

    asyncio.run(run())
    plan_dir = tmp_path / "learning" / "plan"
    assert list(plan_dir.glob("u_*.md")), "plan must be persisted through the MCP tool"
    stored = plan_store.read_plan("default", "u")
    assert stored["frontmatter"]["adjustment_count"] == 1


def test_react_agent_plans_when_no_plan_exists(monkeypatch, tmp_path):
    _patch_graph(monkeypatch, tmp_path)

    call_log = []
    script = [
        # Turn 1: policy says check the stored plan first.
        {
            "content": "先查有没有已保存的规划。",
            "tool_calls": [{"id": "call_1", "name": "get_learning_plan", "arguments": {}}],
            "stop_reason": "tool_calls",
        },
        # Turn 2: no plan → rebuild from the prerequisite graph.
        {
            "content": "没有规划,重新整合。",
            "tool_calls": [{"id": "call_2", "name": "rebuild_learning_plan", "arguments": {"reason": "初次规划"}}],
            "stop_reason": "tool_calls",
        },
        # Turn 3: answer with the rebuilt plan.
        {
            "content": "已生成学习规划:第 1 层 金属键、晶体结构……",
            "tool_calls": [],
            "stop_reason": "stop",
        },
    ]
    turns = iter(script)

    async def fake_llm(system_prompt, messages, tools, **kwargs):
        call_log.append({"tool_names": sorted(t["name"] for t in tools), "last_message": dict(messages[-1])})
        assert "Learning-Plan Policy" in system_prompt
        return next(turns)

    monkeypatch.setattr(react_agent, "chat_complete_tools", fake_llm)

    result = asyncio.run(react_agent.run_react_agent(
        "帮我规划一下学习路径",
        [{"role": "user", "content": "帮我规划一下学习路径"}],
        project_id="default",
    ))

    assert result.answer.startswith("已生成学习规划")
    assert result.tool_calls == 2
    # The rebuild really happened through MCP (real tool handler, fake graph).
    stored = asyncio.run(asyncio.to_thread(plan_store.read_plan, "default", "default"))
    assert stored is not None
    assert "金属键" in stored["markdown"]


def test_react_agent_answers_stored_plan_without_rebuild(monkeypatch, tmp_path):
    _patch_graph(monkeypatch, tmp_path)
    plan_store.write_plan("default", "default", reason="已有规划", overlay=[])

    rebuild_calls = {"count": 0}
    script = [
        {
            "content": "先查规划。",
            "tool_calls": [{"id": "call_1", "name": "get_learning_plan", "arguments": {}}],
            "stop_reason": "tool_calls",
        },
        {
            "content": "规划无实质变化,直接整理返回。",
            "tool_calls": [],
            "stop_reason": "stop",
        },
    ]
    turns = iter(script)

    async def fake_llm(system_prompt, messages, tools, **kwargs):
        return next(turns)

    async def fail_rebuild(*args, **kwargs):
        rebuild_calls["count"] += 1
        raise AssertionError("rebuild must not run when the diff shows no changes")

    import services.learning.plan_store as store_module

    monkeypatch.setattr(store_module, "write_plan", fail_rebuild)
    monkeypatch.setattr(react_agent, "chat_complete_tools", fake_llm)

    result = asyncio.run(react_agent.run_react_agent(
        "我的学习路径是什么?",
        [{"role": "user", "content": "我的学习路径是什么?"}],
        project_id="default",
    ))
    assert result.answer == "规划无实质变化,直接整理返回。"
    assert rebuild_calls["count"] == 0
