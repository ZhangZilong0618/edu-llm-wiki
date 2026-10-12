"""逐学习者推理视图测试(S2)。

核心是多学习者回归:第一阶段审计发现的语义错误(学习者 A 的掌握
让学习者 B 的依赖被误判就绪)必须在隔离视图中消失。
"""

from __future__ import annotations

import pytest

from services.ontology.abox import ABox, OntologyViolation
from services.ontology.reasoning import (
    build_learner_view,
    invalidate_cache,
)


@pytest.fixture()
def abox(tmp_path) -> ABox:
    invalidate_cache()
    box = ABox.open("r_project", path=tmp_path / "onto.sqlite")
    # A --先修--> B --先修--> C;A 迁移至 D;E 与 A 易混淆
    box.assert_atom("Concept", "atom_A", title="概念A")
    box.assert_atom("Formula", "atom_B", title="公式B")
    box.assert_atom("Concept", "atom_C", title="概念C")
    box.assert_atom("Concept", "atom_D", title="概念D")
    box.assert_atom("Concept", "atom_E", title="概念E")
    box.assert_relation("prerequisiteOf", "atom_A", "atom_B")
    box.assert_relation("prerequisiteOf", "atom_B", "atom_C")
    box.assert_relation("transfersTo", "atom_A", "atom_D")
    box.assert_relation("contrastsWith", "atom_A", "atom_E")
    box.add_learner("li1")
    box.add_learner("li2")
    yield box
    box.close()


def test_multi_learner_isolation(abox):
    """审计红项回归:L1 掌握 A 后,L2 的 B 不得被判就绪。"""
    abox.assert_mastery("li1", "atom_A", 0.95)
    invalidate_cache()

    r1 = build_learner_view(abox, "li1")
    assert r1.mastered == ["atom_A"]
    assert "atom_B" in r1.ready            # L1:A 已掌握 → B 就绪
    assert "atom_C" not in r1.ready        # B 未掌握 → C 不就绪
    assert "atom_D" in r1.transfer_candidates

    r2 = build_learner_view(abox, "li2")
    assert r2.mastered == []               # L2 一无所知
    assert "atom_B" not in r2.ready        # 关键:L1 的掌握不再泄漏给 L2
    assert r2.at_risk == []                # 没有迷思痕迹 → 无预警


def test_contrast_rule_in_learner_view(abox):
    """SWRL 迷思预警在学习者视图中正常触发。"""
    abox.assert_misconception_claim("claim_x", distorts="atom_A", title="混淆A")
    abox.add_learner("li3")  # noqa: F841 — 用例内直接复用 li3
    # li3 犯了迷思 claim_x
    with abox.onto:
        abox.onto.MisconceptionTrace(
            "trace_li3", ofLearner=[abox._individual("li3")],
            ofClaim=[abox._individual("claim_x")],
        )
    abox._touch()
    invalidate_cache()

    r = build_learner_view(abox, "li3")
    assert "atom_E" in r.at_risk           # A 的对比伙伴 E 被预警


def test_cache_invalidation(abox):
    abox.assert_mastery("li1", "atom_A", 0.3)   # 未达标
    r1 = build_learner_view(abox, "li1")
    assert r1.mastered == []
    assert "atom_B" not in r1.ready             # A 未掌握 → B 不就绪

    # 修正断言后缓存必须失效并重新推理(同一学习者,结论变化)
    abox.assert_mastery("li1", "atom_A", 0.9)
    r2 = build_learner_view(abox, "li1")
    assert r2 is not r1
    assert r2.mastered == ["atom_A"]
    assert "atom_B" in r2.ready
    assert r2.version > r1.version


def test_unknown_learner_rejected(abox):
    with pytest.raises(OntologyViolation) as e:
        build_learner_view(abox, "ghost")
    assert e.value.code == "missing_individual"


def test_inferred_prerequisites_reported(abox):
    """闭包推断边(A→B、B→C 推出 A→C)单独上报。"""
    abox.assert_mastery("li1", "atom_A", 0.95)
    r = build_learner_view(abox, "li1")
    assert ("atom_A", "atom_C") in r.inferred_prerequisites
    assert r.to_dict()["inferred_prerequisites"] == [
        [s, t] for s, t in r.inferred_prerequisites
    ]
