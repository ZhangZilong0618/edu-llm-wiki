"""ABox 管理层测试(S1)。

覆盖:持久化往返、六类违规断言拦截、冲突关系对、一致性兜底。
每个测试用独立的 tmp 路径,不触碰真实 data/。
"""

from __future__ import annotations

import pytest

from services.ontology.abox import (
    ABox,
    OntologyViolation,
    get_abox,
)


@pytest.fixture()
def abox(tmp_path) -> ABox:
    box = ABox.open("t_project", path=tmp_path / "onto.sqlite")
    yield box
    box.close()


def _seed(box: ABox) -> None:
    box.assert_atom("Concept", "atom_A", title="概念A", difficulty=2)
    box.assert_atom("Formula", "atom_B", title="公式B", difficulty=3)
    box.assert_relation("prerequisiteOf", "atom_A", "atom_B")
    box.assert_source_document("doc_1", filename="lecture.pdf", page_count=42)
    box.assert_relation("teaches", "doc_1", "atom_A")
    box.add_learner("li")
    box.assert_mastery("li", "atom_A", 0.9)


# ---------------------------------------------------------------------------
# 持久化往返
# ---------------------------------------------------------------------------

def test_persistence_roundtrip(tmp_path):
    path = tmp_path / "onto.sqlite"
    box = ABox.open("rt", path=path)
    _seed(box)
    box.close()

    box2 = ABox.open("rt", path=path)
    atoms = {a["name"]: a for a in box2.list_atoms()}
    assert atoms["atom_A"]["title"] == "概念A"
    assert atoms["atom_A"]["type"] == "Concept"
    assert atoms["atom_A"]["difficulty"] == 2
    assert box2.relations_of("atom_A")["prerequisiteOf"] == ["atom_B"]
    assert box2.relations_of("doc_1")["teaches"] == ["atom_A"]
    assert box2.list_learners() == ["li"]
    box2.close()


def test_get_abox_caches_handle(tmp_path):
    a = get_abox("cached", path=tmp_path / "a.sqlite")
    b = get_abox("cached", path=tmp_path / "a.sqlite")
    assert a is b
    a.close()


# ---------------------------------------------------------------------------
# 违规拦截(写入即校验)
# ---------------------------------------------------------------------------

def test_reject_bad_atom_type(abox):
    with pytest.raises(OntologyViolation) as e:
        abox.assert_atom("Synthesis", "atom_x")
    assert e.value.code == "bad_type"


def test_reject_domain_violation(abox):
    _seed(abox)
    # teaches 的定义域是 SourceDocument,原子之间不许 teaches
    with pytest.raises(OntologyViolation) as e:
        abox.assert_relation("teaches", "atom_A", "atom_B")
    assert e.value.code == "domain_violation"


def test_reject_self_loop(abox):
    abox.assert_atom("Concept", "atom_x")
    with pytest.raises(OntologyViolation) as e:
        abox.assert_relation("contrastsWith", "atom_x", "atom_x")
    assert e.value.code == "self_loop"


def test_reject_prerequisite_cycle(abox):
    abox.assert_atom("Concept", "atom_x")
    abox.assert_atom("Concept", "atom_y")
    abox.assert_relation("prerequisiteOf", "atom_x", "atom_y")
    with pytest.raises(OntologyViolation) as e:
        abox.assert_relation("prerequisiteOf", "atom_y", "atom_x")
    assert e.value.code == "cycle"
    # 三角环也要拦:x→y, y→z, z→x
    abox.assert_atom("Concept", "atom_z")
    abox.assert_relation("prerequisiteOf", "atom_y", "atom_z")
    with pytest.raises(OntologyViolation):
        abox.assert_relation("prerequisiteOf", "atom_z", "atom_x")


def test_reject_difficulty_out_of_range(abox):
    with pytest.raises(OntologyViolation) as e:
        abox.assert_atom("Fact", "atom_f", difficulty=6)
    assert e.value.code == "range"


def test_reject_pknown_out_of_range(abox):
    _seed(abox)
    with pytest.raises(OntologyViolation) as e:
        abox.assert_mastery("li", "atom_A", 1.5)
    assert e.value.code == "range"


def test_reject_misconception_without_target(abox):
    _seed(abox)
    # distorts 指向不存在的原子 → missing_individual(而非静默入库)
    with pytest.raises(OntologyViolation) as e:
        abox.assert_misconception_claim("claim_x", distorts="atom_ghost")
    assert e.value.code == "missing_individual"


def test_reject_conflict_pair(abox):
    abox.assert_atom("Concept", "atom_x")
    abox.assert_atom("Concept", "atom_y")
    abox.assert_relation("prerequisiteOf", "atom_x", "atom_y")
    # prerequisiteOf × contrastsWith 同对共存 → 拒绝(任一方向)
    with pytest.raises(OntologyViolation) as e:
        abox.assert_relation("contrastsWith", "atom_x", "atom_y")
    assert e.value.code == "conflict_pair"
    with pytest.raises(OntologyViolation):
        abox.assert_relation("contrastsWith", "atom_y", "atom_x")


def test_reject_unknown_relation(abox):
    _seed(abox)
    with pytest.raises(OntologyViolation) as e:
        abox.assert_relation("isFriendOf", "atom_A", "atom_B")
    assert e.value.code == "unknown_relation"


def test_reject_duplicate(abox):
    _seed(abox)
    with pytest.raises(OntologyViolation) as e:
        abox.assert_atom("Concept", "atom_A")
    assert e.value.code == "duplicate"


def test_mastery_upsert(abox):
    _seed(abox)
    abox.assert_mastery("li", "atom_A", 0.3)  # 同名更新,不新增
    box_ma = abox._individual("ma_li_atom_A")
    assert [float(v) for v in box_ma.pKnown] == [0.3]
    assert abox.version >= 2


# ---------------------------------------------------------------------------
# 一致性兜底
# ---------------------------------------------------------------------------

def test_check_consistency(abox):
    _seed(abox)
    assert abox.check_consistency() is True
