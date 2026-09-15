import asyncio
import json

from services.materials_graph import (
    _normalize_edge_type,
    _normalize_node_type,
    build_relation_candidates,
    extract_materials_graph,
    extract_relations,
)


def test_node_type_aliases_are_normalized():
    assert _normalize_node_type("Principle") == "mechanism"
    assert _normalize_node_type("failure mode") == "failure_mode"
    assert _normalize_node_type("unknown-type") == "concept"


def test_edge_type_aliases_are_normalized():
    assert _normalize_edge_type("structure_to_property") == "determines_property"
    assert _normalize_edge_type("composition_to_structure") == "composition_to_structure"
    assert _normalize_edge_type("algorithm_to_prediction") == "predicted_by"
    assert _normalize_edge_type("not-a-real-edge") == "related"


def test_extract_materials_graph_runs_all_four_stages(monkeypatch):
    content = """
    低碳钢经过淬火与回火后形成马氏体和铁素体。
    晶界阻碍位错运动，因此晶粒细化提高屈服强度。
    XRD 用于表征物相，SEM 用于观察显微组织。
    """

    profile = {
        "course": "材料失效分析",
        "topic": "组织与力学性能",
        "chapters": [{"title": "断裂失效", "summary": "组织决定性能"}],
        "prerequisite_courses": ["材料科学基础"],
        "core_competencies": ["组织-性能分析"],
    }
    nodes = [
        {"label": "低碳钢", "type": "material", "definition": "铁碳合金", "source_ref": "p.1"},
        {"label": "淬火", "type": "processing", "definition": "快速冷却工艺", "source_ref": "p.1"},
        {"label": "马氏体", "type": "structure", "definition": "淬火形成的亚稳相", "source_ref": "p.1"},
        {"label": "位错运动", "type": "mechanism", "definition": "塑性变形的微观机制", "source_ref": "p.1"},
        {"label": "屈服强度", "type": "property", "definition": "材料开始塑性变形的应力", "source_ref": "p.1"},
        {"label": "XRD", "type": "instrument", "definition": "物相表征设备", "source_ref": "p.1"},
    ]
    edges = [
        {"source": "低碳钢", "target": "淬火", "type": "processed_by", "evidence": "经过淬火", "confidence": 0.9},
        {"source": "淬火", "target": "马氏体", "type": "processing_to_structure", "evidence": "形成马氏体", "confidence": 0.9},
        {"source": "位错运动", "target": "屈服强度", "type": "mechanism_to_property", "evidence": "晶界阻碍位错", "confidence": 0.8},
        {"source": "XRD", "target": "马氏体", "type": "characterized_by", "evidence": "XRD表征物相", "confidence": 0.85},
        {"source": "不存在的节点", "target": "屈服强度", "type": "related", "evidence": "invalid", "confidence": 1.0},
    ]
    pedagogy = {
        "nodes": [
            {
                "label": "低碳钢",
                "difficulty": 2,
                "bloom_level": "understand",
                "prerequisites": [],
                "common_misconceptions": [],
                "learning_objectives": ["识别低碳钢"],
                "estimated_minutes": 5,
                "related_courses": ["材料失效分析"],
            },
            {
                "label": "位错运动",
                "difficulty": 4,
                "bloom_level": "analyze",
                "prerequisites": ["晶体缺陷"],
                "common_misconceptions": ["强度和刚度相同"],
                "learning_objectives": ["解释位错对强度的影响"],
                "estimated_minutes": 15,
                "related_courses": ["材料物理性能", "材料失效分析"],
            },
        ]
    }

    async def fake_chat_complete(system_prompt, messages, **kwargs):
        prompt = messages[0]["content"]
        if "curriculum analyst" in prompt:
            return json.dumps(profile, ensure_ascii=False)
        if "knowledge engineer" in prompt:
            return json.dumps({"nodes": nodes}, ensure_ascii=False)
        if "knowledge-graph constructor" in prompt:
            return json.dumps({"edges": edges}, ensure_ascii=False)
        if "materials-science educator" in prompt:
            return json.dumps(pedagogy, ensure_ascii=False)
        raise AssertionError("Unexpected prompt stage")

    monkeypatch.setattr("services.materials_graph.chat_complete", fake_chat_complete)

    graph = asyncio.run(extract_materials_graph(content, source_title="材料失效分析讲义"))

    assert graph["course_profile"]["course"] == "材料失效分析"
    assert len(graph["nodes"]) == 6
    # Four model-verified edges plus one conservative related bridge that
    # connects the processing/structure chain to the mechanism/property chain.
    assert len(graph["edges"]) == 5
    assert graph["stats"]["node_count"] == 6
    assert graph["stats"]["edge_count"] == 5
    assert graph["stats"]["relation_candidate_count"] > 0
    assert graph["stats"]["relation_candidate_coverage"] == 1.0
    assert graph["stats"]["connected_components"] == 1
    assert graph["stats"]["isolated_node_count"] == 0
    assert graph["relation_candidates"]
    bridge = next(edge for edge in graph["edges"] if edge["edge_type"] == "related")
    assert bridge["confidence"] <= 0.45

    labels = {node["label"] for node in graph["nodes"]}
    assert {"低碳钢", "淬火", "马氏体", "位错运动", "屈服强度", "XRD"} == labels

    edge_types = {edge["edge_type"] for edge in graph["edges"]}
    assert {"processed_by", "results_in_structure", "determines_property", "characterized_by"} <= edge_types

    by_label = {node["label"]: node for node in graph["nodes"]}
    assert by_label["位错运动"]["difficulty"] == 4
    assert by_label["位错运动"]["common_misconceptions"] == ["强度和刚度相同"]


def test_json_repair_retry_recovers_from_invalid_response(monkeypatch):
    from services.materials_graph import extract_knowledge_atoms

    profile = {"course": "材料物理性能", "topic": "热导率"}
    content = "热导率由声子散射决定。"
    calls = []

    async def fake_chat_complete(system_prompt, messages, **kwargs):
        calls.append(messages[0]["content"])
        if len(calls) == 1:
            return "这不是 JSON。"
        return '{"nodes": [{"label": "热导率", "type": "property", "definition": "材料导热能力"}]}'

    monkeypatch.setattr("services.materials_graph.chat_complete", fake_chat_complete)
    nodes = asyncio.run(
        extract_knowledge_atoms(content, source_title="材料物理性能", profile=profile)
    )

    assert len(calls) == 2
    assert len(nodes) == 1
    assert nodes[0]["label"] == "热导率"
    assert nodes[0]["node_type"] == "property"


def test_relation_candidates_follow_ontology_and_cover_every_atom():
    content = """
    低碳钢含有碳元素。
    低碳钢经过淬火处理。
    淬火形成马氏体组织。
    马氏体决定屈服强度。
    屈服强度可由位错运动解释。
    XRD 用于表征马氏体。
    """
    nodes = [
        {"id": "steel", "label": "低碳钢", "node_type": "material"},
        {"id": "carbon", "label": "碳元素", "node_type": "composition"},
        {"id": "quench", "label": "淬火", "node_type": "processing"},
        {"id": "martensite", "label": "马氏体", "node_type": "structure"},
        {"id": "yield", "label": "屈服强度", "node_type": "property"},
        {"id": "dislocation", "label": "位错运动", "node_type": "mechanism"},
        {"id": "xrd", "label": "XRD", "node_type": "instrument"},
    ]

    candidates = build_relation_candidates(content, nodes)
    triples = {
        (item["source"], item["target"], item["edge_type"])
        for item in candidates
    }

    expected = {
        ("steel", "carbon", "has_composition"),
        ("steel", "quench", "processed_by"),
        ("quench", "martensite", "results_in_structure"),
        ("martensite", "yield", "determines_property"),
        ("yield", "dislocation", "explained_by"),
        ("martensite", "xrd", "characterized_by"),
    }
    assert expected <= triples

    covered = {item["source"] for item in candidates} | {item["target"] for item in candidates}
    assert covered == {node["id"] for node in nodes}
    assert all(item["evidence"] for item in candidates)
    assert all(0.0 <= item["score"] <= 1.0 for item in candidates)


def test_relation_prompt_contains_candidates_for_model_verification(monkeypatch):
    nodes = [
        {"id": "martensite", "label": "马氏体", "node_type": "structure"},
        {"id": "yield", "label": "屈服强度", "node_type": "property"},
    ]
    candidates = [{
        "source": "martensite",
        "target": "yield",
        "edge_type": "determines_property",
        "evidence": "马氏体决定屈服强度。",
        "score": 0.85,
        "reason": "test candidate",
    }]
    prompts = []

    async def fake_chat_complete(system_prompt, messages, **kwargs):
        prompts.append(messages[0]["content"])
        return '{"edges": []}'

    monkeypatch.setattr("services.materials_graph.chat_complete", fake_chat_complete)
    edges = asyncio.run(extract_relations(
        "马氏体决定屈服强度。",
        source_title="测试文章",
        nodes=nodes,
        relation_candidates=candidates,
    ))

    assert edges == []
    assert "## Relation candidates" in prompts[0]
    assert "马氏体 [martensite] -> 屈服强度 [yield] | determines_property" in prompts[0]
    assert "Relation candidates are hypotheses" in prompts[0]


def test_extract_relations_repairs_reversed_typed_direction(monkeypatch):
    nodes = [
        {"id": "xrd", "label": "XRD", "node_type": "instrument"},
        {"id": "martensite", "label": "马氏体", "node_type": "structure"},
    ]

    async def fake_chat_complete(system_prompt, messages, **kwargs):
        return json.dumps({
            "edges": [{
                "source": "XRD",
                "target": "马氏体",
                "type": "characterized_by",
                "evidence": "XRD表征马氏体",
                "confidence": 0.9,
            }]
        }, ensure_ascii=False)

    monkeypatch.setattr("services.materials_graph.chat_complete", fake_chat_complete)
    edges = asyncio.run(extract_relations(
        "XRD表征马氏体。",
        source_title="测试文章",
        nodes=nodes,
    ))

    assert len(edges) == 1
    assert edges[0]["source"] == "martensite"
    assert edges[0]["target"] == "xrd"
    assert edges[0]["edge_type"] == "characterized_by"


def test_extract_relations_upgrades_related_to_typed_candidate(monkeypatch):
    nodes = [
        {"id": "hydrogen_embrittlement", "label": "氢脆", "node_type": "failure_mode"},
        {"id": "hydrogen_mechanism", "label": "氢致韧性下降", "node_type": "mechanism"},
    ]
    candidates = [{
        "source": "hydrogen_embrittlement",
        "target": "hydrogen_mechanism",
        "edge_type": "explained_by",
        "evidence": "氢进入金属后造成韧性下降",
        "score": 0.9,
        "reason": "same-sentence co-occurrence + type-compatible relation",
    }]

    async def fake_chat_complete(system_prompt, messages, **kwargs):
        return json.dumps({
            "edges": [{
                "source": "氢脆",
                "target": "氢致韧性下降",
                "type": "related",
                "evidence": "氢进入金属后造成韧性下降",
                "confidence": 0.8,
            }]
        }, ensure_ascii=False)

    monkeypatch.setattr("services.materials_graph.chat_complete", fake_chat_complete)
    edges = asyncio.run(extract_relations(
        "氢脆是氢进入金属后造成韧性下降。",
        source_title="测试文章",
        nodes=nodes,
        relation_candidates=candidates,
    ))

    assert len(edges) == 1
    assert edges[0]["edge_type"] == "explained_by"
    assert edges[0]["source"] == "hydrogen_embrittlement"
    assert edges[0]["target"] == "hydrogen_mechanism"
