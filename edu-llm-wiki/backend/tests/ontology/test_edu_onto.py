"""EDU-ONTO 本体的形式性质测试。

推理类测试每个都会启动一次 HermiT(Java 子进程,~2-4s/次)。
schema 锁定测试防止本体被无意改动。

运行(backend/ 目录下,需要 Java 运行时):
    python3 -m pytest tests/ontology/ -q
"""

from __future__ import annotations

import pytest
from owlready2 import OwlReadyInconsistentOntologyError, World

from services.ontology import (
    MASTERY_THRESHOLD,
    PAGE_TEMPLATES,
    RELATION_SPECS,
    build_ontology,
)
from services.ontology.materialize import materialize_learner_view


def fresh_ontology():
    """隔离 World 上的全新本体(测试互不污染)。"""
    return build_ontology(world=World())


def _sync(onto):
    """HermiT 推理并回传结果。

    owlready2 的 ``infer_property_values`` 默认 False:不显式打开,
    HermiT 内部照常应用 SWRL 规则,但结论不会回传 Python 世界。
    """
    from owlready2 import sync_reasoner

    return sync_reasoner(onto, infer_property_values=True, debug=0)


# ---------------------------------------------------------------------------
# Schema 锁定(无推理,快)
# ---------------------------------------------------------------------------

def test_schema_locked():
    """类/属性/个体数量与预期一致 —— 本体 schema 漂移的守卫。"""
    onto = fresh_ontology()
    assert len(list(onto.classes())) == 38
    assert len(list(onto.object_properties())) == 34
    assert len(list(onto.data_properties())) == 12
    assert len(list(onto.individuals())) == 9  # 3 维度 + 6 认知层级
    assert len(RELATION_SPECS) == 31
    assert len(PAGE_TEMPLATES) == 13


def test_disjointness_axioms_present():
    """四组互斥公理必须写进 quadstore(owlready2 不暴露逐对 disjointWith,
    经 SPARQL 查 AllDisjointClasses;语义生效性另由 typeclash 推理测试保证)。"""
    onto = fresh_ontology()
    rows = list(onto.world.sparql(
        "SELECT ?x WHERE { ?x rdf:type <http://www.w3.org/2002/07/owl#AllDisjointClasses> }"
    ))
    assert len(rows) == 4  # 六原子类 / 断言子类 / 制品子类 / 顶层大类


def test_build_idempotent():
    onto1 = fresh_ontology()
    onto2 = fresh_ontology()
    assert len(list(onto1.classes())) == len(list(onto2.classes()))


# ---------------------------------------------------------------------------
# 推理(每个测试启动一次 HermiT)
# ---------------------------------------------------------------------------

def test_tbox_consistent():
    """空 ABox 的 TBox 必须一致。"""
    onto = fresh_ontology()
    _sync(onto)


def _build_normal_abox(onto):
    """A --先修--> B --先修--> C;A 迁移至 D;E 与 A 易混淆;A 已掌握。"""
    with onto:
        a = onto.Concept("atom_carrier")
        b = onto.Formula("atom_ohm_formula")
        c = onto.Concept("atom_resistance")
        d = onto.Concept("atom_semiconductor")
        e = onto.Concept("atom_hole")
        a.prerequisiteOf = [b]
        b.prerequisiteOf = [c]
        a.transfersTo = [d]
        a.contrastsWith = [e]

        learner = onto.Learner("learner_li")
        ma = onto.MasteryAssertion("ma_li_A", ofLearner=[learner], ofAtom=[a])
        ma.pKnown = [float(MASTERY_THRESHOLD) + 0.05]

        mc = onto.MisconceptionClaim("claim_confuse_direction", distorts=[a])
        onto.MisconceptionTrace("trace_li_1", ofLearner=[learner], ofClaim=[mc])
    return a, b, c, d, e, learner


def test_pedagogical_reasoning():
    """MasteredAtom / ReadyAtom / TransferCandidate / SWRL 预警全部正确。"""
    onto = fresh_ontology()
    _build_normal_abox(onto)
    materialize_learner_view(onto)
    _sync(onto)

    mastered = {i.name for i in onto.MasteredAtom.instances()}
    ready = {i.name for i in onto.ReadyAtom.instances()}
    transfer = {i.name for i in onto.TransferCandidate.instances()}
    learner = onto.learner_li
    at_risk = {o.name for o in learner.atRiskOfConfusing}

    assert "atom_carrier" in mastered                     # A 已掌握
    assert "atom_ohm_formula" in ready                    # B 就绪(先修 A 已掌握)
    assert "atom_resistance" not in ready                 # C 不就绪(先修 B 未掌握)
    assert "atom_semiconductor" in transfer               # D 迁移候选
    assert "atom_hole" in at_risk                         # SWRL 迷思预警
    # SWRL 传递闭包:A→B、B→C 应推出 A→C(a 先修于 c)
    assert "atom_resistance" in {o.name for o in onto.atom_carrier.prerequisiteOf}


def test_prerequisite_cycle_inconsistent():
    """先修环 → 本体不一致(DAG 形式不变量)。"""
    onto = fresh_ontology()
    with onto:
        x = onto.Concept("atom_x")
        y = onto.Concept("atom_y")
        x.prerequisiteOf = [y]
        y.prerequisiteOf = [x]
    with pytest.raises(OwlReadyInconsistentOntologyError):
        _sync(onto)


def test_atom_type_clash_inconsistent():
    """同个体断言两种互斥原子类型 → 不一致。"""
    onto = fresh_ontology()
    with onto:
        rogue = onto.Concept("rogue_atom")
        rogue.is_a.append(onto.Formula)
    with pytest.raises(OwlReadyInconsistentOntologyError):
        _sync(onto)


def test_distorts_range_violation_inconsistent():
    """distorts 指向非知识原子 → 不一致(值域公理)。"""
    onto = fresh_ontology()
    with onto:
        page = onto.WikiPage("page_a")
        onto.MisconceptionClaim("claim_bad", distorts=[page])
    with pytest.raises(OwlReadyInconsistentOntologyError):
        _sync(onto)


def test_contrasts_self_loop_inconsistent():
    """自混淆(contrastsWith 自环)→ 不一致(对称+反自反)。"""
    onto = fresh_ontology()
    with onto:
        x = onto.Concept("atom_x")
        x.contrastsWith = [x]
    with pytest.raises(OwlReadyInconsistentOntologyError):
        _sync(onto)


def test_transfers_self_loop_inconsistent():
    """自迁移(transfersTo 自环)→ 不一致(反自反)。"""
    onto = fresh_ontology()
    with onto:
        x = onto.Concept("atom_x")
        x.transfersTo = [x]
    with pytest.raises(OwlReadyInconsistentOntologyError):
        _sync(onto)


def test_difficulty_out_of_range_inconsistent():
    """难度越界(6 > 上限 5)→ 不一致(数据区间约束)。"""
    onto = fresh_ontology()
    with onto:
        x = onto.Concept("atom_x")
        x.difficulty = [6]
    with pytest.raises(OwlReadyInconsistentOntologyError):
        _sync(onto)


def test_generalizes_cycle_inconsistent():
    """上位环(A 推广 B、B 推广 A)→ 不一致(反自反 + SWRL 传递)。"""
    onto = fresh_ontology()
    with onto:
        x = onto.Concept("atom_x")
        y = onto.Concept("atom_y")
        x.generalizes = [y]
        y.generalizes = [x]
    with pytest.raises(OwlReadyInconsistentOntologyError):
        _sync(onto)


def test_derives_self_loop_inconsistent():
    """自推导 → 不一致(反自反直接抓获)。"""
    onto = fresh_ontology()
    with onto:
        x = onto.Formula("formula_x")
        x.derivesFrom = [x]
    with pytest.raises(OwlReadyInconsistentOntologyError):
        _sync(onto)


def test_dimension_definition_classifies():
    """维度定义类自动给原子归类(Bloom 维度传播)。"""
    onto = fresh_ontology()
    with onto:
        onto.Concept("atom_a")
        onto.Procedure("atom_p")
    _sync(onto)
    conceptual = {i.name for i in onto.ConceptualKnowledge.instances()}
    procedural = {i.name for i in onto.ProceduralKnowledge.instances()}
    assert "atom_a" in conceptual
    assert "atom_p" in procedural
    assert "atom_a" not in procedural


# ---------------------------------------------------------------------------
# OWA 边界(校验层职责,无推理)
# ---------------------------------------------------------------------------

def test_missing_distorts_caught_by_validator():
    """缺 distorts 的迷思:推理器不报(OWA),校验层必须抓住。"""
    onto = fresh_ontology()
    with onto:
        onto.MisconceptionClaim("claim_no_target")
    missing = [
        c.name for c in onto.MisconceptionClaim.instances() if not list(c.distorts)
    ]
    assert missing == ["claim_no_target"]
