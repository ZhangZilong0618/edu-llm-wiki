"""每项目 ABox 管理层(v4 · 第二阶段 S1)。

每项目一个 owlready2 SQLite 四元库:
``data/projects/{pid}/ontology.sqlite``(与 graph.sqlite 并列)。
TBox(EDU-ONTO)首次打开时构建进该库,重复打开幂等。

**写入即校验**:所有断言先过校验器,不合法立即抛
:class:`OntologyViolation`(code/message/details 结构化,供 S4 的 LLM
修复回路直接消费),绝不静默入库。校验项:

- 原子/制品类型合法;
- 关系存在、两端个体存在、定义域/值域匹配(含子类闭包);
- 反自反关系拒绝自环;
- 四条结构关系(prerequisiteOf/partOf/derivesFrom/generalizes)拒绝成环
  ——DAG 不变量的前置检查,推理时的 SWRL 规则是兜底而非唯一防线;
- 冲突关系对拒绝同对共存(prerequisiteOf×contrastsWith、
  derivesFrom×generalizes,docs/wiki-redesign.md §0.5.3);
- 数据区间(difficulty 1..5,pKnown 0..1);
- 迷思断言必须带 distorts 目标(开放世界下推理器不查,由本层强制)。

与 graph_store 的分工:OWL 库存形式三元组;graph_edges 侧车存
weight/origin/evidence 等非逻辑元数据(第二阶段 S4 对齐)。
"""

from __future__ import annotations

import re
from pathlib import Path

from owlready2 import (
    OwlReadyInconsistentOntologyError,
    World,
    locstr,
    sync_reasoner,
)

from services.ontology.edu_onto import (
    DATA_PROPERTY_NAMES,
    KNOWLEDGE_CLASS_NAMES,
    RELATION_SPECS,
    build_ontology,
)

#: 五个知识原子类型
ATOM_TYPES = KNOWLEDGE_CLASS_NAMES

#: 结构关系:断言时做环检查(推理时另有 SWRL 闭包规则兜底)
STRUCTURAL_RELATIONS = ("prerequisiteOf", "partOf", "derivesFrom", "generalizes")

#: 同对节点不允许共存的关系对(冲突矩阵,docs/wiki-redesign.md §0.5.3)
CONFLICT_PAIRS = (
    frozenset({"prerequisiteOf", "contrastsWith"}),
    frozenset({"derivesFrom", "generalizes"}),
)

_EVENT_CLASSES = {"exposure": "ExposureEvent", "attempt": "AttemptEvent",
                  "review": "ReviewEvent"}

_SPEC_BY_NAME = {s.name: s for s in RELATION_SPECS}

_NAME_RE = re.compile(r"^[\w\u4e00-\u9fff][\w\u4e00-\u9fff\-]*$")


class OntologyViolation(Exception):
    """校验失败的断言。结构化信息供修复回路定位问题。"""

    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def abox_path(project_id: str, *, base_dir: str | Path | None = None) -> Path:
    """项目 ABox 的 SQLite 路径(测试可传 base_dir 隔离)。"""
    if base_dir is not None:
        base = Path(base_dir)
    else:
        from config import settings

        base = Path(settings.projects_dir)
    path = base / project_id / "ontology.sqlite"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


class ABox:
    """一个项目的 ABox 句柄。用 :meth:`open` / :func:`get_abox` 获取。"""

    def __init__(self, project_id: str, world: World, path: Path):
        self.project_id = project_id
        self.world = world
        self.path = path
        self.onto = build_ontology(world=world)
        #: 写计数——逐学习者推理缓存用它判断失效
        self.version = 0

    # ------------------------------------------------------------------
    # 打开 / 关闭
    # ------------------------------------------------------------------

    @classmethod
    def open(cls, project_id: str, *, path: str | Path | None = None) -> "ABox":
        p = Path(path) if path is not None else abox_path(project_id)
        return cls(project_id, World(filename=str(p)), p)

    @classmethod
    def scratch(cls, project_id: str = "scratch") -> "ABox":
        """内存态 ABox(不落盘)——校验回路/测试用,断言失败可整体丢弃。"""
        box = cls.__new__(cls)
        box.project_id = project_id
        box.world = World()
        box.path = None
        box.onto = build_ontology(world=box.world)
        box.version = 0
        return box

    def close(self) -> None:
        # World 的 sqlite 后端不自动提交:必须 save() 落盘再关
        self.world.save()
        self.world.close()
        _OPEN.pop(self.project_id, None)

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    def _individual(self, name: str):
        """按名取个体;类/属性/不存在都返回 None(owlready2 中类是 type)。"""
        obj = getattr(self.onto, name, None)
        if obj is None or isinstance(obj, type):
            return None
        return obj

    @staticmethod
    def _prop_values(ind, prop_name: str) -> list:
        """读个体的属性值;sqlite 重载后未赋值属性可能是 None 而非 []。"""
        values = getattr(ind, prop_name, None)
        return list(values) if values else []

    def _class_closure(self, ind) -> set[str]:
        """个体全部断言类及其命名祖先(供定义域/值域检查)。

        祖先表来自 TBox 构建时算好的 edu_ancestor_map:owlready2 的
        .ancestors() 只走断言 subClassOf,经 equivalent_to 蕴含的
        维度类 ⊑ KnowledgeAtom 在断言闭包里不可见。
        """
        ancestor_map = getattr(self.onto, "edu_ancestor_map", {})
        out: set[str] = set()
        for cls in ind.is_a:
            if not isinstance(cls, type):
                continue
            out.add(cls.name)
            out.update(ancestor_map.get(cls.name, set()))
        return out

    def _check_side(self, spec, ind, side: str) -> None:
        allowed = getattr(spec, side)
        if not allowed:
            return
        classes = self._class_closure(ind)
        if not classes & set(allowed):
            raise OntologyViolation(
                f"{side}_violation",
                f"关系 {spec.name} 的{ '定义域' if side == 'domain' else '值域' }"
                f"要求 {'/'.join(allowed)},个体 {ind.name} 属于 {sorted(classes)}",
                {"relation": spec.name, "individual": ind.name, "side": side,
                 "allowed": list(allowed)},
            )

    def _would_cycle(self, relation: str, source: str, target: str) -> bool:
        """新边 source→target 后,若 target 经已有边可达 source 则成环。"""
        stack, seen = [target], set()
        while stack:
            cur = stack.pop()
            if cur == source:
                return True
            if cur in seen:
                continue
            seen.add(cur)
            ind = self._individual(cur)
            if ind is None:
                continue
            stack.extend(
                o.name for o in self._prop_values(ind, relation) if hasattr(o, "name")
            )
        return False

    def _check_conflicts(self, relation: str, source: str, target: str) -> None:
        for pair in CONFLICT_PAIRS:
            if relation not in pair:
                continue
            other = next(iter(pair - {relation}))
            s_ind, t_ind = self._individual(source), self._individual(target)
            s_others = {o.name for o in self._prop_values(s_ind, other) if hasattr(o, "name")}
            t_others = {o.name for o in self._prop_values(t_ind, other) if hasattr(o, "name")}
            if target in s_others or source in t_others:
                raise OntologyViolation(
                    "conflict_pair",
                    f"{relation} 与 {other} 不允许同对共存:{source} ↔ {target}",
                    {"relation": relation, "conflicts_with": other,
                     "pair": [source, target]},
                )

    def _require(self, name: str, what: str):
        ind = self._individual(name)
        if ind is None:
            raise OntologyViolation(
                "missing_individual", f"{what}不存在:{name}", {"name": name}
            )
        return ind

    def _check_name(self, name: str) -> None:
        if not _NAME_RE.match(name or ""):
            raise OntologyViolation(
                "bad_name",
                f"非法实体名 {name!r}:仅允许字母/数字/下划线/连字符/中文",
                {"name": name},
            )

    def _touch(self) -> None:
        self.version += 1
        # 写入即提交(sqlite 后端不自动落盘;批量导入时可优化为显式批量提交)
        self.world.save()

    # ------------------------------------------------------------------
    # 写入(全部先校验)
    # ------------------------------------------------------------------

    def assert_atom(self, atom_type: str, name: str, *, title: str | None = None,
                    difficulty: int | None = None) -> Any:
        """断言一个知识原子。title 写入 zhLabel(Protégé 兼容策略)。"""
        if atom_type not in ATOM_TYPES:
            raise OntologyViolation(
                "bad_type", f"非法原子类型 {atom_type!r},允许:{list(ATOM_TYPES)}",
                {"atom_type": atom_type, "allowed": list(ATOM_TYPES)},
            )
        self._check_name(name)
        if self._individual(name) is not None:
            raise OntologyViolation(
                "duplicate", f"个体已存在:{name}", {"name": name}
            )
        if difficulty is not None and not (1 <= int(difficulty) <= 5):
            raise OntologyViolation(
                "range", f"difficulty 越界:{difficulty}(1..5)",
                {"field": "difficulty", "value": difficulty},
            )
        cls = getattr(self.onto, atom_type)
        with self.onto:
            ind = cls(name)
            if title is not None:
                ind.zhLabel = [locstr(title, lang="zh")]
            if difficulty is not None:
                ind.difficulty = [int(difficulty)]
        self._touch()
        return ind

    def assert_relation(self, relation: str, source: str, target: str) -> None:
        """断言对象属性(方向:source →target,按 RelationSpec 语义)。"""
        spec = _SPEC_BY_NAME.get(relation)
        if spec is None:
            raise OntologyViolation(
                "unknown_relation", f"未知关系 {relation!r}",
                {"relation": relation,
                 "allowed": sorted(_SPEC_BY_NAME)},
            )
        s = self._require(source, "关系起点")
        t = self._require(target, "关系终点")
        self._check_side(spec, s, "domain")
        self._check_side(spec, t, "range")
        if source == target and spec.irreflexive:
            raise OntologyViolation(
                "self_loop", f"{relation} 不允许自环:{source}",
                {"relation": relation, "node": source},
            )
        if relation in STRUCTURAL_RELATIONS and self._would_cycle(relation, source, target):
            raise OntologyViolation(
                "cycle", f"{relation} 成环:{source} → {target} 会闭合环路",
                {"relation": relation, "source": source, "target": target},
            )
        self._check_conflicts(relation, source, target)
        with self.onto:
            setattr(s, relation, self._prop_values(s, relation) + [t])
        self._touch()

    def assert_source_document(self, name: str, *, filename: str,
                               page_count: int | None = None) -> Any:
        self._check_name(name)
        if self._individual(name) is not None:
            raise OntologyViolation("duplicate", f"个体已存在:{name}", {"name": name})
        with self.onto:
            doc = self.onto.SourceDocument(name, fileName=[filename])
            if page_count is not None:
                doc.pageCount = [int(page_count)]
        self._touch()
        return doc

    def assert_misconception_claim(self, name: str, *, distorts: str,
                                   title: str | None = None) -> Any:
        """迷思断言:必须指明被扭曲的原子(OWA 下推理器不查,本层强制)。"""
        self._check_name(name)
        if self._individual(name) is not None:
            raise OntologyViolation("duplicate", f"个体已存在:{name}", {"name": name})
        target = self._require(distorts, "被扭曲的原子")
        with self.onto:
            claim = self.onto.MisconceptionClaim(name, distorts=[target])
            if title is not None:
                claim.zhLabel = [locstr(title, lang="zh")]
        self._touch()
        return claim

    def add_learner(self, name: str) -> Any:
        self._check_name(name)
        if self._individual(name) is not None:
            raise OntologyViolation("duplicate", f"个体已存在:{name}", {"name": name})
        with self.onto:
            ind = self.onto.Learner(name)
        self._touch()
        return ind

    def assert_mastery(self, learner: str, atom: str, p_known: float) -> None:
        """掌握断言(同名则更新 pKnown——BKT 每次输出都落这里)。"""
        if not (0.0 <= float(p_known) <= 1.0):
            raise OntologyViolation(
                "range", f"pKnown 越界:{p_known}(0..1)",
                {"field": "pKnown", "value": p_known},
            )
        l = self._require(learner, "学习者")
        a = self._require(atom, "掌握的原子")
        name = f"ma_{learner}_{atom}"
        existing = self._individual(name)
        with self.onto:
            if existing is not None:
                existing.pKnown = [float(p_known)]
            else:
                self.onto.MasteryAssertion(
                    name, ofLearner=[l], ofAtom=[a], pKnown=[float(p_known)]
                )
        self._touch()

    def record_event(self, learner: str, event_type: str, atom: str, *,
                     timestamp=None, **data) -> Any:
        """学习事件(exposure/attempt/review)。"""
        if event_type not in _EVENT_CLASSES:
            raise OntologyViolation(
                "bad_type", f"非法事件类型 {event_type!r}",
                {"event_type": event_type, "allowed": sorted(_EVENT_CLASSES)},
            )
        l = self._require(learner, "学习者")
        a = self._require(atom, "事件针对的原子")
        name = f"ev_{learner}_{event_type}_{atom}_{self.version}"
        cls = getattr(self.onto, _EVENT_CLASSES[event_type])
        with self.onto:
            ev = cls(name, ofLearner=[l], aboutAtom=[a])
            if timestamp is not None:
                ev.timestamp = [timestamp]
            for key in ("confidenceResidual",):
                if key in data and data[key] is not None:
                    setattr(ev, key, [float(data[key])])
        self._touch()
        return ev

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def _title_of(self, ind) -> str | None:
        for v in getattr(ind, "zhLabel", []) or []:
            return str(v)
        return None

    def list_atoms(self, atom_type: str | None = None) -> list[dict]:
        """列出原子 [{name, type, title, difficulty}](按类型/名称排序)。"""
        types = [atom_type] if atom_type else list(ATOM_TYPES)
        out = []
        for t in types:
            for ind in getattr(self.onto, t).instances():
                out.append({
                    "name": ind.name,
                    "type": t,
                    "title": self._title_of(ind),
                    "difficulty": next(iter(ind.difficulty or []), None),
                })
        return sorted(out, key=lambda x: (x["type"], x["name"]))

    def find_atom_by_title(self, title: str) -> dict | None:
        for atom in self.list_atoms():
            if atom["title"] == title:
                return atom
        return None

    def get_atom(self, name: str) -> dict | None:
        for atom in self.list_atoms():
            if atom["name"] == name:
                return atom
        return None

    def relations_of(self, name: str) -> dict[str, list[str]]:
        """个体作为主语的全部已断言关系 {relation: [targets]}。"""
        ind = self._require(name, "个体")
        out: dict[str, list[str]] = {}
        for spec in RELATION_SPECS:
            targets = [
                o.name for o in self._prop_values(ind, spec.name) if hasattr(o, "name")
            ]
            if targets:
                out[spec.name] = targets
        return out

    def list_learners(self) -> list[str]:
        return sorted(i.name for i in self.onto.Learner.instances())

    # ------------------------------------------------------------------
    # 一致性
    # ------------------------------------------------------------------

    def check_consistency(self) -> bool:
        """全库 HermiT 一致性检查(写入侧校验的兜底)。"""
        try:
            sync_reasoner(self.onto, debug=0)
            return True
        except OwlReadyInconsistentOntologyError:
            return False


_OPEN: dict[str, ABox] = {}


def get_abox(project_id: str, *, path: str | Path | None = None) -> ABox:
    """进程内缓存的项目 ABox 句柄(同一 SQLite 文件不能并发多写)。"""
    if project_id not in _OPEN:
        _OPEN[project_id] = ABox.open(project_id, path=path)
    return _OPEN[project_id]
