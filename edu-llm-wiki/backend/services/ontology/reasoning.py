"""逐学习者推理视图(v4 · 第二阶段 S2)。

**为什么必须逐学习者**:``MasteredAtom`` 的 DL 定义是"存在**任一**学习
者的达标断言"——学习者无关。多用户共享推理会把别人的掌握当成你的
(审计实测:L1 掌握 A 后,L2 的依赖 B 也被误判"就绪")。DL 类无法按
学习者参数化,正确做法是**隔离视图**:每个学习者一个内存 World =
TBox + 项目共享原子/关系 + 仅该学习者的掌握断言/事件/迷思痕迹,
物化后单独推理。

共享 ABox 里按学习者过滤是**不健全**的:其他学习者的断言仍会使原子
被分类 MasteredAtom,与物化断言的 ¬MasteredAtom 冲突 → 假不一致。
所以这里把视图内容**复制**到独立 World,绝不在源库上动手术。

缓存:按 (project_id, learner) 缓存推理结果,以 ABox.version(写计数)
为失效条件——该学习者或共享图的任何写入都会使缓存失效。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from owlready2 import World, sync_reasoner

from services.ontology.abox import ABox
from services.ontology.edu_onto import (
    DATA_PROPERTY_NAMES,
    RELATION_SPECS,
    build_ontology,
)
from services.ontology.materialize import materialize_learner_view

#: 复制到视图的共享类(全部实例整体复制)
_SHARED_CLASSES = (
    "Fact", "Concept", "Principle", "Formula", "Procedure",   # 原子
    "SourceDocument",                                            # 来源
    "MisconceptionClaim",                                        # 迷思断言
)
#: 仅复制当前学习者实例的类
_LEARNER_CLASSES = (
    "MasteryAssertion",
    "ExposureEvent", "AttemptEvent", "ReviewEvent",
    "MisconceptionTrace",
)


@dataclass
class ReasoningResult:
    """一次逐学习者推理的结论。"""

    learner: str
    project_id: str
    version: int
    mastered: list[str] = field(default_factory=list)
    ready: list[str] = field(default_factory=list)
    transfer_candidates: list[str] = field(default_factory=list)
    at_risk: list[str] = field(default_factory=list)
    #: SWRL 传递闭包推出的先修边 [(prereq, dependent), ...]
    inferred_prerequisites: list[tuple[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "learner": self.learner,
            "project_id": self.project_id,
            "mastered": self.mastered,
            "ready": self.ready,
            "transfer_candidates": self.transfer_candidates,
            "at_risk": self.at_risk,
            "inferred_prerequisites": [
                [s, t] for s, t in self.inferred_prerequisites
            ],
        }


_CACHE: dict[tuple[str, str], ReasoningResult] = {}


def invalidate_cache(project_id: str | None = None, learner: str | None = None) -> None:
    """手动清缓存(测试用;正常运行靠 version 失效)。"""
    if project_id is None:
        _CACHE.clear()
        return
    keys = [k for k in _CACHE
            if k[0] == project_id and (learner is None or k[1] == learner)]
    for k in keys:
        _CACHE.pop(k, None)


def copy_project(src_onto, dst_onto) -> dict[str, tuple[Any, Any]]:
    """复制项目的全部业务个体与关系(不含 TBox 个体)到目标本体。

    学习者视图与派生层的 scratch 校验共用。
    """
    classes = _SHARED_CLASSES + ("Learner",) + _LEARNER_CLASSES
    created = _copy_individuals(src_onto, dst_onto, classes)
    _copy_relations(src_onto, dst_onto, created)
    return created


def _copy_individuals(src, dst, class_names: tuple[str, ...]) -> dict[str, tuple[Any, Any]]:
    """按类复制个体(含数据属性),返回 name→(源个体, 新个体)。"""
    created: dict[str, tuple[Any, Any]] = {}
    for cls_name in class_names:
        for ind in getattr(src, cls_name).instances():
            if ind.name in created:
                continue
            new = getattr(dst, cls_name)(ind.name)
            for prop in DATA_PROPERTY_NAMES:
                values = list(getattr(ind, prop, None) or [])
                if values:
                    setattr(new, prop, list(values))
            created[ind.name] = (ind, new)
    return created


def _copy_relations(src, dst, created: dict[str, tuple[Any, Any]],
                    subset: dict[str, tuple[Any, Any]] | None = None,
                    ) -> set[tuple[str, str]]:
    """复制 subset(默认 created)内个体间的已断言对象属性。

    返回 prerequisiteOf 的断言边集合(推理后用来区分闭包推断边)。
    """
    asserted_prereq: set[tuple[str, str]] = set()
    scope = created if subset is None else subset
    for name, (src_ind, s_new) in scope.items():
        for spec in RELATION_SPECS:
            targets = getattr(src_ind, spec.name, None) or []
            for target in targets:
                if not hasattr(target, "name") or target.name not in created:
                    continue
                t_new = created[target.name][1]
                existing = list(getattr(s_new, spec.name, None) or [])
                if t_new not in existing:
                    setattr(s_new, spec.name, existing + [t_new])
                if spec.name == "prerequisiteOf":
                    asserted_prereq.add((name, target.name))
    return asserted_prereq


def build_learner_view(abox: ABox, learner: str, *, use_cache: bool = True,
                       keep_world: bool = False) -> ReasoningResult:
    """构建某学习者的隔离推理视图并返回结论。

    keep_world=True 时视图世界挂在结果对象上(_view_world 属性),
    供调用方进一步查询;否则推理后即释放。
    """
    key = (abox.project_id, learner)
    cached = _CACHE.get(key)
    if use_cache and cached is not None and cached.version == abox.version:
        return cached

    if learner not in abox.list_learners():
        from services.ontology.abox import OntologyViolation

        raise OntologyViolation(
            "missing_individual", f"学习者不存在:{learner}", {"name": learner}
        )

    world = World()
    onto = build_ontology(world=world)

    # 1) 共享层:原子/来源/迷思断言 + 全部学习者(仅作个体存在)
    created = _copy_individuals(abox.onto, onto, _SHARED_CLASSES + ("Learner",))

    # 2) 该学习者的掌握断言/事件/迷思痕迹(重建而非过滤——隔离视图,
    #    其他学习者的断言绝不进入本视图)
    learner_specific: dict[str, tuple[Any, Any]] = {}
    for cls_name in _LEARNER_CLASSES:
        for ind in getattr(abox.onto, cls_name).instances():
            owners = [
                o.name for o in (getattr(ind, "ofLearner", None) or [])
                if hasattr(o, "name")
            ]
            if learner not in owners:
                continue
            new = getattr(onto, cls_name)(ind.name)
            for prop in DATA_PROPERTY_NAMES:
                values = list(getattr(ind, prop, None) or [])
                if values:
                    setattr(new, prop, list(values))
            learner_specific[ind.name] = (ind, new)
    created.update(learner_specific)

    # 3) 关系:共享层一遍、学习者层一遍(ofLearner/ofAtom/ofClaim/aboutAtom)
    asserted_prereq = _copy_relations(abox.onto, onto, created)
    _copy_relations(abox.onto, onto, created, subset=learner_specific)

    # 4) 物化(OWA 局部闭世界)+ HermiT 推理
    materialize_learner_view(onto)
    sync_reasoner(onto, infer_property_values=True, debug=0)

    learner_ind = created[learner][1]
    mastered = sorted(i.name for i in onto.MasteredAtom.instances())
    ready = sorted(i.name for i in onto.ReadyAtom.instances())
    transfer = sorted(i.name for i in onto.TransferCandidate.instances())
    at_risk = sorted(
        {o.name for o in (getattr(learner_ind, "atRiskOfConfusing", None) or [])
         if hasattr(o, "name")}
    )
    inferred: list[tuple[str, str]] = []
    for ind in onto.KnowledgeAtom.instances():
        for o in getattr(ind, "prerequisiteOf", None) or []:
            if hasattr(o, "name") and (ind.name, o.name) not in asserted_prereq:
                inferred.append((ind.name, o.name))
    inferred.sort()

    result = ReasoningResult(
        learner=learner,
        project_id=abox.project_id,
        version=abox.version,
        mastered=mastered,
        ready=ready,
        transfer_candidates=transfer,
        at_risk=at_risk,
        inferred_prerequisites=inferred,
    )
    if keep_world:
        result._view_world = world  # noqa: SLF001 — 显式保留供查询
    else:
        world.close()
    _CACHE[key] = result
    return result
