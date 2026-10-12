"""逐学习者物化协议 —— 开放世界假设(OWA)的工程落地。

OWL 推理器是开放世界:未断言 ≠ 不存在。``ReadyAtom``/``TransferCandidate``
定义里的 ¬MasteredAtom 分量、``∀hasPrerequisite.MasteredAtom`` 的全称量词,
都需要对学习者视图做**局部闭世界**才能被 HermiT 分类:

1. **未掌握显式化**:对每个尚无达标掌握断言的原子,显式断言
   ``Not(MasteredAtom)`` —— 让 ¬Mastered 分量可证。
2. **先修集封闭**:对每个原子断言 ``hasPrerequisite.only(OneOf(传递闭包))``
   (空集时用 ``only(Nothing)``)—— 阻止 HermiT 想象未知的未掌握先修,
   使全称量词可证。注意闭包必须覆盖 SWRL 传递规则推出的间接先修边。

调用时机:ABox 断言完成后、``sync_reasoner(onto, infer_property_values=True)``
之前。

**多学习者契约(重要)**:``MasteredAtom`` 的定义是"存在**任一**学习者的
达标断言"——学习者无关。因此本函数只在**单学习者 ABox**(或"共享掌握"
语义可接受时)正确;多用户场景必须在**逐学习者的隔离视图**上调用
(每个学习者一个 World:TBox + 共享原子 + 仅该学习者的断言)。
在共享 ABox 里按学习者过滤是**不健全**的:其他学习者的达标断言仍会使
原子被分类为 MasteredAtom,与断言的 ¬MasteredAtom 冲突 → 假不一致。
逐学习者视图的构建属于第二阶段 ABox 管理层的职责。
"""

from __future__ import annotations

from owlready2 import Not, Nothing, OneOf

from services.ontology.edu_onto import MASTERY_THRESHOLD


def _asserted_atoms(onto) -> list:
    """六个具体原子类的全部已断言个体。"""
    atoms: list = []
    for cls_name in ("Fact", "Concept", "Principle", "Formula", "Procedure"):
        atoms.extend(getattr(onto, cls_name).instances())
    # 去重(同个体可能被断言到多个具体类的极端情况下)
    return list({a.name: a for a in atoms}.values())


def _prerequisite_closure(atoms: list) -> dict[str, list]:
    """从已断言的 prerequisiteOf 边计算每个原子的传递闭包先修集。

    注意方向:``pre.prerequisiteOf = [dep]`` 读作 "pre 先修于 dep",
    即 **dep 的先修包含 pre** —— prerequisiteOf 的值是下游依赖者,
    收集某原子的先修要看指向它的边,而不是它的属性值。
    """
    by_name = {a.name: a for a in atoms}
    direct: dict[str, list[str]] = {a.name: [] for a in atoms}
    for pre in atoms:
        for dependent in getattr(pre, "prerequisiteOf", []):
            if hasattr(dependent, "name") and dependent.name in by_name:
                direct[dependent.name].append(pre.name)

    closure: dict[str, set[str]] = {}

    def _close(name: str) -> set[str]:
        if name in closure:
            return closure[name]
        closure[name] = set()  # 先占位防环(数据环留给推理器判不一致)
        result: set[str] = set()
        for pre in direct[name]:
            result.add(pre)
            result |= _close(pre)
        closure[name] = result
        return result

    return {name: sorted(_close(name)) for name in direct}


def materialize_learner_view(onto) -> dict:
    """对整个 ABox 做局部闭世界物化,返回物化统计。

    掌握阈值固定取本体常量 ``MASTERY_THRESHOLD`` —— 不作为参数暴露:
    MasteredAtom 类定义里的数据区间写死了同一常量,允许调用方传不同
    阈值会造成"物化说未掌握、推理器说已掌握"的静默矛盾。

    返回 ``{"mastered": [...], "unmastered": [...], "prereq_closure": {...}}``。
    幂等:重复断言同一公理无副作用(owlready2 去重)。
    """
    atoms = _asserted_atoms(onto)
    mastery_threshold = float(MASTERY_THRESHOLD)

    # 已达标的原子:pKnown ≥ 阈值 的掌握断言所指向的原子
    mastered: set[str] = set()
    for ma in onto.MasteryAssertion.instances():
        values = [v for v in (ma.pKnown or []) if isinstance(v, (int, float))]
        if any(v >= mastery_threshold for v in values):
            for atom in getattr(ma, "ofAtom", []):
                if hasattr(atom, "name"):
                    mastered.add(atom.name)

    unmastered: list[str] = []
    for atom in atoms:
        if atom.name not in mastered:
            atom.is_a.append(Not(onto.MasteredAtom))
            unmastered.append(atom.name)

    closure = _prerequisite_closure(atoms)
    by_name = {a.name: a for a in atoms}
    for name, prereq_names in closure.items():
        if name not in by_name:
            continue
        if prereq_names:
            restriction = onto.hasPrerequisite.only(
                OneOf([by_name[n] for n in prereq_names if n in by_name])
            )
        else:
            restriction = onto.hasPrerequisite.only(Nothing)
        by_name[name].is_a.append(restriction)

    return {
        "mastered": sorted(mastered),
        "unmastered": sorted(unmastered),
        "prereq_closure": closure,
    }
