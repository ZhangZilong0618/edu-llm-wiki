"""EDU-ONTO 教育学本体 —— 单一事实来源(single source of truth)。

三层分离设计 v1.1:

1. 知识原子层(KnowledgeAtom):五类,对齐 Bloom 修订分类知识维度
   (Anderson & Krathwohl, 2001)中**可从源文档抽取**的三维:
   事实/概念/公式(概念性)+ 方法(程序性)。
   Bloom 的第四维"元认知知识"被有意排除:领域讲义不含"如何学习"的
   内容,该维无法回溯源文档(违反证据链不变量),且系统内无消费者。
2. 知识断言层(KnowledgeClaim):认识态度独立成轴 —— 迷思断言必须指明
   它扭曲哪个正确原子;LLM 生成但未通过引用校验的内容标记为待验证断言。
3. 教学制品层(EducationalArtifact):页面是知识的载体,不是知识本身。
   例题、探究、学习路径、量规都是制品,经 manifests/exemplifies 等关系
   联到知识原子。

页面模板(concept_page/formula_page/...)是从本体**派生**的展示概念,
不是本体类 —— 由 ``PAGE_TEMPLATES`` 登记,生成层与渲染层据此映射。

关键公理:
- ``prerequisiteOf``/``partOf`` 反自反 + **SWRL 传递规则**:OWL 2 的
  regularity 条件禁止传递属性声明反自反(非简单属性),传递闭包因此由
  SWRL 规则实现;先修环经规则推导出 a→a 后被反自反公理抓获 ——
  先修图必须是 DAG 仍是形式不变量;
- 六个原子类两两互斥 → 生成时类型标错直接被一致性检查抓住;
- ``MisconceptionClaim ⊑ ∃distorts.KnowledgeAtom`` → 迷思必须指向它扭曲的对象;
- ``ReadyAtom ≡ ¬MasteredAtom ⊓ ∀hasPrerequisite.MasteredAtom`` → 前沿节点
  是公理的推论,不再由 BFS 硬算。

开放世界妥协:``ReadyAtom``/``TransferCandidate`` 的 ¬MasteredAtom 分量在
逐学习者物化视图上求值(推理服务负责显式断言未掌握),见 validate_ontology.py。

运行 HermiT 需要 Java 运行时(owlready2 内置推理器 jar)。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from owlready2 import (
    AllDisjoint,
    AllDifferent,
    AnnotationProperty,
    ConstrainedDatatype,
    DatatypeProperty,
    FunctionalProperty,
    Imp,
    IrreflexiveProperty,
    locstr,
    Not,
    ObjectProperty,
    Or,
    SymmetricProperty,
    Thing,
    TransitiveProperty,
    World,
)

BASE_IRI = "https://edu-llm-wiki.org/ontology/edu-onto"
VERSION = "1.1"

#: 掌握阈值。与 mastery.py 的 MASTERY_THRESHOLD 语义一致;本体侧用它
#: 定义 MasteredAtom 的数据区间(≥ 该值为已掌握)。
MASTERY_THRESHOLD = Decimal("0.85")


# ---------------------------------------------------------------------------
# 页面模板注册表 —— 从本体派生的展示概念(不是本体类)
# ---------------------------------------------------------------------------

#: template_id -> (承载的本体类, 中文标签)
PAGE_TEMPLATES: dict[str, tuple[str, str]] = {
    "fact_page": ("Fact", "事实页"),
    "concept_page": ("Concept", "概念页"),
    "principle_page": ("Principle", "原理页"),
    "formula_page": ("Formula", "公式页"),
    "procedure_page": ("Procedure", "方法页"),
    "example_page": ("Example", "例题页"),
    "misconception_page": ("MisconceptionClaim", "迷思页"),
    "inquiry_page": ("Inquiry", "探究页"),
    "objective_page": ("LearningObjective", "目标页"),
    "path_page": ("LearningPath", "路径页"),
    "rubric_page": ("Rubric", "量规页"),
    "guide_page": ("Guide", "指引页"),
    "source_page": ("SourceDocument", "来源页"),
}


# ---------------------------------------------------------------------------
# 关系规格 —— 声明式定义,构建时应用到本体,同时作为对外导出的元数据
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RelationSpec:
    name: str
    zh: str
    domain: tuple[str, ...] = ()          # 多于一个类名 = 定义域取并集;空 = 不限
    range: tuple[str, ...] = ()           # 同上
    transitive: bool = False
    symmetric: bool = False
    irreflexive: bool = False
    functional: bool = False
    inverse_of: str | None = None         # 在本属性上声明 owl:inverseOf
    rationale: str = ""                   # 学理依据(写入 rdfs:comment)

    @property
    def characteristics(self) -> list[str]:
        out = []
        if self.transitive:
            out.append("transitive")
        if self.symmetric:
            out.append("symmetric")
        if self.irreflexive:
            out.append("irreflexive")
        if self.functional:
            out.append("functional")
        return out


#: 结构关系(A 组)+ 教学关系(B 组)+ 元关系(C 组)+ 断言/制品/学习者连接关系
RELATION_SPECS: tuple[RelationSpec, ...] = (
    # — A. 结构关系:知识本身的内在结构 —
    RelationSpec(
        "prerequisiteOf", "先修于", ("KnowledgeAtom",), ("KnowledgeAtom",),
        irreflexive=True, inverse_of="hasPrerequisite",
        rationale="A prerequisiteOf B:不会 A 就无法理解 B(Anderson 1983 图式;"
                 "Sweller 1988 认知负荷)。反自反 + SWRL 传递规则(OWL 2 禁止"
                 "传递属性声明反自反),先修环成为本体级不一致。",
    ),
    RelationSpec(
        "derivesFrom", "推导自", ("Formula", "Principle"), ("Formula", "Principle"),
        irreflexive=True,
        rationale="A 由 B 经数学/逻辑推导得到(Polya 1945 形式化推理链)。"
                 "同 prerequisiteOf:反自反 + SWRL 传递规则,推导环即不一致。",
    ),
    RelationSpec(
        "partOf", "部分于", ("KnowledgeAtom",), ("KnowledgeAtom",),
        irreflexive=True,
        rationale="A 是 B 的组成部分(整体-部分图式,Mandler 1992)。"
                 "同 prerequisiteOf:反自反 + SWRL 传递规则。",
    ),
    RelationSpec(
        "generalizes", "推广", ("KnowledgeAtom",), ("KnowledgeAtom",),
        irreflexive=True,
        rationale="A 是 B 的上位抽象(Gentner 1983 结构映射,高阶图式)。"
                 "同 prerequisiteOf:反自反 + SWRL 传递规则,层级环即不一致。",
    ),
    RelationSpec(
        "specificCaseOf", "特例于", ("KnowledgeAtom",), ("KnowledgeAtom",),
        rationale="A 是 B 的具体特例(Rosch 1973 基本层次范畴),如常数卡"
                 "特例于其所属概念。与 generalizes 独立:特例含'具体例子',"
                 "抽象层级推不出特例。命名避开 OWL 自身的 instance-of"
                 "(个体↔类)——本关系连接两个原子(个体↔个体)。",
    ),
    RelationSpec(
        "formalizes", "形式化", ("Formula",), ("Principle",),
        rationale="连接同一规律的符号表达(公式)与言语陈述(原理),"
                 "消解公式页/原理页内容重复。",
    ),
    # — B. 教学关系:学习顺序与支架 —
    RelationSpec(
        "teaches", "讲授", ("SourceDocument",), ("KnowledgeAtom",),
        rationale="来源文档承载知识(van Dijk & Kintsch 1983 篇章结构)。",
    ),
    RelationSpec(
        "scaffolds", "支架", ("KnowledgeAtom",), ("KnowledgeAtom",),
        irreflexive=True,
        rationale="A 是理解 B 的过渡台阶(Vygotsky 1978 ZPD;"
                 "Wood, Bruner & Ross 1976 scaffolding)。自支架无意义。",
    ),
    RelationSpec(
        "exemplifies", "示例化", ("Example",), ("KnowledgeAtom",),
        rationale="用具体材料演示知识的使用(Sweller & Cooper 1985 变样例效应)。",
    ),
    RelationSpec(
        "recalls", "记忆钩", ("KnowledgeAtom",), ("KnowledgeAtom",),
        irreflexive=True,
        rationale="口诀/类比/图像式记忆辅助(Bower 1970 意象与言语编码)。",
    ),
    # — C. 元关系:对比、迁移、引用 —
    RelationSpec(
        "contrastsWith", "易混淆", ("KnowledgeAtom",), ("KnowledgeAtom",),
        symmetric=True, irreflexive=True,
        rationale="A 与 B 容易混淆,对比能避免迷思(Brown & Burton 1978 故障模型;"
                 "Chi 1992 概念变更)。对称;自混淆无意义。",
    ),
    RelationSpec(
        "transfersTo", "迁移至", ("KnowledgeAtom",), ("KnowledgeAtom",),
        irreflexive=True, inverse_of="receivedTransferFrom",
        rationale="学会 A 后正向迁移加速 B(Singley & Anderson 1989 认知技能迁移)。",
    ),
    RelationSpec(
        "reviews", "复习入口", ("KnowledgeAtom",), ("KnowledgeAtom",),
        irreflexive=True,
        rationale="用 A 来复习 B(Bjork 1994 必要难度;间隔效应 Cepeda 2006)。",
    ),
    RelationSpec(
        "references", "引用", (), (),
        rationale="正文 wikilink 解析出的纯引用,无教学声明,弱兜底(Landow 1992)。",
    ),
    # — 断言层连接 —
    RelationSpec(
        "distorts", "扭曲", ("MisconceptionClaim",), ("KnowledgeAtom",),
        rationale="迷思断言扭曲的正确知识对象。",
    ),
    RelationSpec(
        "afflicts", "侵害", ("MisconceptionTaxon",), ("KnowledgeAtom",),
        rationale="迷思分类作用的原子类别。",
    ),
    RelationSpec(
        "ofClaim", "属断言", ("MisconceptionTrace",), ("MisconceptionClaim",),
        rationale="学习者的迷思痕迹指向具体断言。",
    ),
    # — 制品层连接 —
    RelationSpec(
        "manifests", "载体化", ("WikiPage",),
        ("KnowledgeAtom", "Example", "Inquiry", "LearningObjective",
         "LearningPath", "Rubric", "Guide", "KnowledgeClaim"),
        rationale="维基页面是知识/断言/制品的载体。页面不是知识。",
    ),
    RelationSpec(
        "drawsOn", "取材于", ("WikiPage", "KnowledgeAtom", "KnowledgeClaim"),
        ("SourceDocument",),
        rationale="证据链:一切生成内容回溯到来源文档。",
    ),
    RelationSpec(
        "assesses", "评测", ("AssessmentItem",), ("KnowledgeAtom",),
        rationale="评测项考察的原子。",
    ),
    RelationSpec(
        "targetsAtom", "目标针对", ("LearningObjective",), ("KnowledgeAtom",),
        rationale="学习目标对齐的原子(constructive alignment)。",
    ),
    RelationSpec(
        "hasStep", "含步骤", ("LearningPath",), ("PathStep",),
        rationale="学习路径的有序步骤。",
    ),
    RelationSpec(
        "stepAtom", "步骤针对", ("PathStep",), ("KnowledgeAtom",),
        rationale="路径步骤指向的原子。",
    ),
    RelationSpec(
        "nextStep", "后继步骤", ("PathStep",), ("PathStep",),
        rationale="步骤顺序链。",
    ),
    # — 学习者层连接 —
    RelationSpec(
        "ofLearner", "属学习者", ("MasteryAssertion", "LearningEvent", "MisconceptionTrace"),
        ("Learner",),
        rationale="掌握断言/学习事件/迷思痕迹归属的学习者。",
    ),
    RelationSpec(
        "ofAtom", "针对原子", ("MasteryAssertion",), ("KnowledgeAtom",),
        inverse_of="masteredBy",
        rationale="掌握断言针对的原子。",
    ),
    RelationSpec(
        "aboutAtom", "关于原子", ("LearningEvent",), ("KnowledgeAtom",),
        rationale="学习事件(接触/作答/复习)针对的原子。",
    ),
    RelationSpec(
        "performed", "执行", ("Learner",), ("LearningEvent",),
        rationale="学习者执行的学习事件。",
    ),
    RelationSpec(
        "atRiskOfConfusing", "有混淆风险", ("Learner",), ("KnowledgeAtom",),
        rationale="推理器经 ContrastRisk SWRL 规则推断:在 A 上犯过迷思的学习者"
                 "对 contrastsWith(A) 的伙伴原子有混淆风险。",
    ),
    # — Bloom 对齐 —
    RelationSpec(
        "hasKnowledgeDimension", "知识维度", ("KnowledgeAtom",), ("KnowledgeDimension",),
        functional=True,
        rationale="Bloom 修订分类知识维度(函数属性:每个原子恰一维)。",
    ),
    RelationSpec(
        "hasCognitiveLevel", "认知层级", ("LearningObjective", "AssessmentItem"),
        ("CognitiveProcessLevel",),
        rationale="Bloom 修订分类认知过程维度。",
    ),
)

#: 数据属性规格:name -> (zh, domain 类名元组, python 类型)
#: 注:owlready2 将 float 序列化为 xsd:decimal;不要用 decimal.Decimal
#: (owlready2 的 range 归一化不识别它)。
_DATA_PROPERTY_SPECS: tuple[tuple[str, str, tuple[str, ...], object], ...] = (
    ("pKnown", "掌握概率", ("MasteryAssertion",), float),
    ("confidenceResidual", "置信残差", ("AttemptEvent",), float),
    ("difficulty", "难度", ("KnowledgeAtom",), int),
    ("estimatedMinutes", "预计分钟", ("KnowledgeAtom",), float),
    ("hasTemplate", "页面模板", ("WikiPage",), str),
    ("hasEpistemicStatus", "认识状态", ("KnowledgeClaim",), str),
    ("stepIndex", "步骤序号", ("PathStep",), int),
    ("fileName", "文件名", ("SourceDocument",), str),
    ("pageCount", "页数", ("SourceDocument",), int),
    ("pagePath", "页面路径", ("WikiPage",), str),
    ("contentHash", "内容哈希", ("WikiPage",), str),
    ("timestamp", "时间戳", ("LearningEvent",), datetime),
)

#: 数据属性名(ABox 复制/派生层遍历用)
DATA_PROPERTY_NAMES = tuple(name for name, *_ in _DATA_PROPERTY_SPECS)

#: 五个知识原子类名(断言层/复制层的稳定字面量)
KNOWLEDGE_CLASS_NAMES = ("Fact", "Concept", "Principle", "Formula", "Procedure")

#: 数据区间约束(比裸类型更严):难度 1..5,掌握概率 0..1。
#: 区间违反会像类型违反一样被一致性检查抓获。
#: 惰性构建:ConstrainedDatatype 须在本体上下文内创建。
_DATA_RANGE_BUILDERS = {
    "difficulty": lambda: ConstrainedDatatype(int, min_inclusive=1, max_inclusive=5),
    "pKnown": lambda: ConstrainedDatatype(float, min_inclusive=0.0, max_inclusive=1.0),
}


# ---------------------------------------------------------------------------
# 构建函数
# ---------------------------------------------------------------------------

def _ensure_zh_label_property(onto) -> None:
    """Ensure the annotation property used by the UI labels exists.

    Databases created before the label annotation was introduced can still be
    opened by :class:`ABox`; creating the property lazily keeps that migration
    path safe.
    """
    prop = getattr(onto, "zhLabel", None)
    if prop is not None:
        return
    with onto:
        label_property = type("zhLabel", (AnnotationProperty,), {})
        setattr(onto, "zhLabel", label_property)


def _ensure_teaching_taxonomy(onto) -> None:
    """Merge the v2 TeachingObject taxonomy into the v1 runtime ontology.

    The ABox and reasoning services still use the v1 ontology IRI and class
    names.  The Wiki directory, however, is generated from the v2 taxonomy.
    This compatibility layer makes both views describe the same World: old
    classes keep their existing parents and receive the corresponding v2 group
    as an additional parent; missing v2 classes are created below that group.
    The import is deliberately lazy so v1 remains importable in isolation.
    """
    from services.ontology_v2 import TEACHING_CLASS_GROUPS, validate_teaching_taxonomy

    # Fail early if the source-of-truth mapping itself is malformed.  The
    # ontology-free validation is independent of the v1/v2 IRI distinction.
    validate_teaching_taxonomy()

    with onto:
        teaching_root = getattr(onto, "TeachingObject", None)
        if not isinstance(teaching_root, type):
            teaching_root = type("TeachingObject", (Thing,), {})
            setattr(onto, "TeachingObject", teaching_root)

        groups: dict[str, type] = {}
        for group_name in TEACHING_CLASS_GROUPS:
            group = getattr(onto, group_name, None)
            if not isinstance(group, type):
                group = type(group_name, (teaching_root,), {})
                setattr(onto, group_name, group)
            elif teaching_root not in group.is_a:
                group.is_a.append(teaching_root)
            groups[group_name] = group

        for group_name, metadata in TEACHING_CLASS_GROUPS.items():
            parent = groups[group_name]
            for class_name in metadata["classes"]:
                cls = getattr(onto, class_name, None)
                if not isinstance(cls, type):
                    cls = type(class_name, (parent,), {})
                    setattr(onto, class_name, cls)
                elif parent not in cls.is_a:
                    # Multiple inheritance is intentional for the four v1
                    # classes (Learner, LearningEvent, LearningObjective and
                    # LearningPath): their old semantics remain intact while
                    # the v2 directory gets a stable classification parent.
                    cls.is_a.append(parent)


def build_ontology(*, world: World | None = None):
    """程序化构建 EDU-ONTO TBox 并返回 owlready2 ontology 对象。

    传入隔离的 ``World`` 可获得相互独立的本体实例(测试场景用)。
    幂等:同一 world 重复调用返回已构建的本体。
    """
    onto = (world or World()).get_ontology(BASE_IRI)
    if list(onto.classes()):  # 已构建(注意 classes() 返回生成器,不能直接作真值)
        # ABox 世界可能是从旧版 ontology.sqlite 重载的。不能因为已有
        # TBox 就直接返回，否则运行时会缺少新版 Wiki 目录所依赖的
        # TeachingObject 分类。补齐分类后重建派生祖先表，保持旧推理
        # 类和关系不变。
        _ensure_teaching_taxonomy(onto)
        _ensure_zh_label_property(onto)
        _apply_labels_and_comments(onto)
        for cls in onto.classes():
            if Thing in cls.is_a:
                cls.is_a.remove(Thing)
        onto.edu_ancestor_map = _compute_ancestor_map(onto)
        onto._edu_version = VERSION
        return onto

    with onto:
        # ---- 第一层:知识原子 ----
        class KnowledgeAtom(Thing):
            pass

        # 六个具体原子类先以 KnowledgeAtom 平级子类创建(属性定义阶段要
        # 引用它们);对维度定义类的归属延后到 is_a 追加,打破循环依赖。
        class Fact(KnowledgeAtom):
            pass

        class Concept(KnowledgeAtom):
            pass

        class Principle(KnowledgeAtom):
            pass

        class Formula(KnowledgeAtom):
            pass

        class Procedure(KnowledgeAtom):
            pass

        class KnowledgeDimension(Thing):
            pass

        class CognitiveProcessLevel(Thing):
            pass

        # ---- 第二层:知识断言 ----
        class KnowledgeClaim(Thing):
            pass

        class MisconceptionClaim(KnowledgeClaim):
            pass

        class UnverifiedClaim(KnowledgeClaim):
            pass

        class LearnerBelief(KnowledgeClaim):
            pass

        # ---- 第三层:教学制品 ----
        class EducationalArtifact(Thing):
            pass

        class SourceDocument(EducationalArtifact):
            pass

        class WikiPage(EducationalArtifact):
            pass

        class Example(EducationalArtifact):
            pass

        class Inquiry(EducationalArtifact):
            pass

        class LearningObjective(EducationalArtifact):
            pass

        class LearningPath(EducationalArtifact):
            pass

        class Rubric(EducationalArtifact):
            pass

        class Guide(EducationalArtifact):
            pass

        class PathStep(Thing):
            pass

        # ---- 学习者与评价模型 ----
        class Learner(Thing):
            pass

        class MasteryAssertion(Thing):
            pass

        class LearningEvent(Thing):
            pass

        class ExposureEvent(LearningEvent):
            pass

        class AttemptEvent(LearningEvent):
            pass

        class ReviewEvent(LearningEvent):
            pass

        class MisconceptionTrace(Thing):
            pass

        class AssessmentItem(Thing):
            pass

        class MisconceptionTaxon(Thing):
            pass

    classes = {c.__name__: c for c in onto.classes()}

    # ---- 对象属性 ----
    with onto:
        # 先建仅作互逆引用的属性,specs 循环里的 inverse_property 才能引用到
        for inv_name in ("hasPrerequisite", "receivedTransferFrom", "masteredBy"):
            p = type(inv_name, (ObjectProperty,), {})
            if not hasattr(onto, inv_name):
                setattr(onto, inv_name, p)
            # OWLViz 兼容:rdfs:label 保持 ASCII,中文延后在
            # _apply_labels_and_comments 写入 zhLabel
            p.label = [locstr(inv_name, lang="en")]

        for spec in RELATION_SPECS:
            # owlready2 把 domain=[A,B] 序列化为两条 rdfs:domain,OWL 语义是
            # **交集** —— 多类必须包成 Or([...]) 单条并集,否则互斥类的
            # "定义域交集"是空类,任何断言都会被判不一致。
            body = {}
            if spec.domain:
                ents = [classes[n] for n in spec.domain]
                body["domain"] = ents if len(ents) == 1 else [Or(ents)]
            if spec.range:
                ents = [classes[n] for n in spec.range]
                body["range"] = ents if len(ents) == 1 else [Or(ents)]
            if spec.inverse_of:
                body["inverse_property"] = getattr(onto, spec.inverse_of)
            prop = type(spec.name, (ObjectProperty,), body)
            if not hasattr(onto, spec.name):
                setattr(onto, spec.name, prop)
            # 形式特征经 is_a 追加(owlready2 的声明方式)
            if spec.transitive:
                prop.is_a.append(TransitiveProperty)
            if spec.symmetric:
                prop.is_a.append(SymmetricProperty)
            if spec.irreflexive:
                prop.is_a.append(IrreflexiveProperty)
            if spec.functional:
                prop.is_a.append(FunctionalProperty)

        # ---- 数据属性 ----
        for name, _zh, domain_names, py_type in _DATA_PROPERTY_SPECS:
            rng = _DATA_RANGE_BUILDERS[name]() if name in _DATA_RANGE_BUILDERS else py_type
            dprop = type(name, (DatatypeProperty,), {
                "domain": [classes[n] for n in domain_names],
                "range": [rng],
            })
            if not hasattr(onto, name):
                setattr(onto, name, dprop)
            dprop.label = [locstr(name, lang="en")]

    # ---- Bloom 个体 ----
    # 元认知维度(dimMetacognitive)被有意排除:领域文档不含元认知内容,
    # 该维度无来源也无消费者(见模块 docstring)。
    with onto:
        dim_factual = classes["KnowledgeDimension"]("dimFactual")
        dim_conceptual = classes["KnowledgeDimension"]("dimConceptual")
        dim_procedural = classes["KnowledgeDimension"]("dimProcedural")
        level_names = ("lvRemember", "lvUnderstand", "lvApply",
                       "lvAnalyze", "lvEvaluate", "lvCreate")
        levels = [classes["CognitiveProcessLevel"](n) for n in level_names]
        for ind, zh in zip(
            (dim_factual, dim_conceptual, dim_procedural),
            ("事实性", "概念性", "程序性"),
        ):
            ind.label = [locstr(zh, lang="zh")]
        for ind, zh in zip(
            levels, ("记忆", "理解", "应用", "分析", "评价", "创造"),
        ):
            ind.label = [locstr(zh, lang="zh")]

    # ---- 定义类:维度类(性质决定类)----
    # hasKnowledgeDimension 是函数属性 → 三个维度类自动两两互斥。
    has_dim = getattr(onto, "hasKnowledgeDimension")
    dimension_definitions = {
        "FactualKnowledge": ("dimFactual", "事实性知识", dim_factual),
        "ConceptualKnowledge": ("dimConceptual", "概念性知识", dim_conceptual),
        "ProceduralKnowledge": ("dimProcedural", "程序性知识", dim_procedural),
    }
    with onto:
        for cls_name, (_ind_name, _zh, ind) in dimension_definitions.items():
            defined = type(cls_name, (Thing,), {})
            defined.equivalent_to = [KnowledgeAtom & has_dim.value(ind)]
            setattr(onto, cls_name, defined)

        # ---- 五个原子类的 Bloom 维度归属 ----
        # 维度类是**唯一**的直接父类:Fact ⊑ FactualKnowledge。
        # 不再断言 Fact ⊑ KnowledgeAtom(经维度类间接可达,是冗余断言),
        # 也不再单独挂 ∃维度 值公理(经维度类的定义已蕴含)。
        # 原因:断言的 KnowledgeAtom 父类会与推理得出的维度父类并存,
        # Protégé 树里同一个类出现在两个位置;单一直接父类则两个视图
        # (断言树/推理树)都只出现一次。
        atom_dimension_class = {
            "Fact": "FactualKnowledge",
            "Concept": "ConceptualKnowledge",
            "Principle": "ConceptualKnowledge",
            "Formula": "ConceptualKnowledge",
            "Procedure": "ProceduralKnowledge",
        }
        for atom_name, dim_name in atom_dimension_class.items():
            atom_cls = getattr(onto, atom_name)
            if KnowledgeAtom in atom_cls.is_a:
                atom_cls.is_a.remove(KnowledgeAtom)
            atom_cls.is_a.append(getattr(onto, dim_name))

        # ---- 定义类:迷思强制指向被扭曲对象 ----
        distorts = getattr(onto, "distorts")
        MisconceptionClaim.is_a.append(distorts.some(KnowledgeAtom))

        # ---- 定义类:教学推理(MasteredAtom / ReadyAtom / TransferCandidate) ----
        # 三个类按"学习者状态轴"收纳在 LearnerStatusAtom 之下。它们与
        # Fact/Concept/... 的"知识类型轴"正交(被掌握的原子依然是概念或
        # 公式),不组织的话会在推理树中与五个原子类并列,混淆两条分类轴。
        # 注意:三个类的定义与 KnowledgeAtom 相交,⊑ KnowledgeAtom 是
        # 推理器必然得出的结论,无法"挪出"——中间父类只做层次组织,
        # 不改变推理语义。
        class LearnerStatusAtom(KnowledgeAtom):
            pass

        mastered_by = getattr(onto, "masteredBy")
        p_known = getattr(onto, "pKnown")
        has_prerequisite = getattr(onto, "hasPrerequisite")
        received_transfer = getattr(onto, "receivedTransferFrom")

        mastered_datum = ConstrainedDatatype(float, min_inclusive=float(MASTERY_THRESHOLD))
        MasteredAtom = type("MasteredAtom", (LearnerStatusAtom,), {})
        MasteredAtom.equivalent_to = [
            KnowledgeAtom
            & mastered_by.some(
                getattr(onto, "MasteryAssertion") & p_known.some(mastered_datum)
            )
        ]
        setattr(onto, "MasteredAtom", MasteredAtom)

        ReadyAtom = type("ReadyAtom", (LearnerStatusAtom,), {})
        ReadyAtom.equivalent_to = [
            KnowledgeAtom
            & Not(MasteredAtom)
            & has_prerequisite.only(MasteredAtom)
        ]
        setattr(onto, "ReadyAtom", ReadyAtom)

        TransferCandidate = type("TransferCandidate", (LearnerStatusAtom,), {})
        TransferCandidate.equivalent_to = [
            KnowledgeAtom
            & Not(MasteredAtom)
            & received_transfer.some(MasteredAtom)
        ]
        setattr(onto, "TransferCandidate", TransferCandidate)

    # ---- 互斥公理 ----
    AllDisjoint([
        getattr(onto, n) for n in
        ("Fact", "Concept", "Principle", "Formula", "Procedure")
    ])
    AllDisjoint([
        getattr(onto, n) for n in
        ("MisconceptionClaim", "UnverifiedClaim", "LearnerBelief")
    ])
    AllDisjoint([
        getattr(onto, n) for n in
        ("SourceDocument", "WikiPage", "Example", "Inquiry",
         "LearningObjective", "LearningPath", "Rubric", "Guide")
    ])
    AllDisjoint([
        getattr(onto, n) for n in
        ("KnowledgeAtom", "KnowledgeClaim", "EducationalArtifact", "Learner",
         "MasteryAssertion", "LearningEvent", "MisconceptionTrace",
         "AssessmentItem", "MisconceptionTaxon")
    ])
    AllDifferent([dim_factual, dim_conceptual, dim_procedural])
    AllDifferent(list(levels))

    # ---- SWRL 规则 ----
    # R1–R4 传递闭包:OWL 2 regularity 条件禁止传递属性声明反自反,
    # 传递性由规则实现。环 a→b→a 经规则推出 a→a,反自反公理随即判不一致;
    # 单点自环则被反自反直接抓获。四条结构关系(prerequisiteOf/partOf/
    # derivesFrom/generalizes)全部是 DAG 不变量。
    # R5 迷思对比预警:
    #   MisconceptionTrace(?t) ∧ ofLearner(?t,?l) ∧ ofClaim(?t,?c)
    #     ∧ distorts(?c,?a) ∧ contrastsWith(?a,?b) → atRiskOfConfusing(?l,?b)
    with onto:
        prereq_transitivity = Imp()
        prereq_transitivity.set_as_rule(
            "prerequisiteOf(?a, ?b), prerequisiteOf(?b, ?c) "
            "-> prerequisiteOf(?a, ?c)"
        )
        prereq_transitivity.label = [locstr("先修传递闭包规则", lang="zh")]

        partof_transitivity = Imp()
        partof_transitivity.set_as_rule(
            "partOf(?a, ?b), partOf(?b, ?c) -> partOf(?a, ?c)"
        )
        partof_transitivity.label = [locstr("部分传递闭包规则", lang="zh")]

        derives_transitivity = Imp()
        derives_transitivity.set_as_rule(
            "derivesFrom(?a, ?b), derivesFrom(?b, ?c) -> derivesFrom(?a, ?c)"
        )
        derives_transitivity.label = [locstr("推导传递闭包规则", lang="zh")]

        generalizes_transitivity = Imp()
        generalizes_transitivity.set_as_rule(
            "generalizes(?a, ?b), generalizes(?b, ?c) -> generalizes(?a, ?c)"
        )
        generalizes_transitivity.label = [locstr("上位传递闭包规则", lang="zh")]

        contrast_rule = Imp()
        contrast_rule.set_as_rule(
            "MisconceptionTrace(?t), ofLearner(?t, ?l), ofClaim(?t, ?c), "
            "distorts(?c, ?a), contrastsWith(?a, ?b) "
            "-> atRiskOfConfusing(?l, ?b)"
        )
        contrast_rule.label = [locstr("迷思对比预警规则", lang="zh")]

    # ---- 标签与学理注释 ----
    # Protégé 兼容性:rdfs:label 只放英文。OWLViz(Protégé 自带类图插件)
    # 把渲染名导出为 Graphviz DOT,其老式词法分析器遇到 CJK 字符直接抛
    # Lexical error——中文标签放 zhLabel 注解,rdfs:label 保持 ASCII。
    # 本系统读中文一律走 RELATION_SPECS / _CLASS_LABELS,不依赖 rdfs:label。
    # 想在 Protégé 里看中文:View → Render by annotation → 选 zhLabel。
    with onto:
        class zhLabel(AnnotationProperty):
            pass
    # v2 教学应用对象层与 v1 知识/推理层共用同一 World。追加分类只
    # 增加父类关系和缺失类，不改动 v1 的类、属性、公理或推理规则。
    _ensure_teaching_taxonomy(onto)
    _apply_labels_and_comments(onto)

    # ---- 清除显式 subClassOf owl:Thing ----
    # owlready2 用 `class X(Thing)` 建根类,Python 继承动作会字面生成
    # subClassOf 三元组并序列化。OWL 中任何类都隐含 ⊑ Thing,显式声明
    # 是纯冗余,且让 Protégé 类描述面板多出多余的 Thing 父类条目。
    for cls in onto.classes():
        if Thing in cls.is_a:
            cls.is_a.remove(Thing)

    # ---- 命名祖先表(供 ABox 层的定义域/值域检查)----
    # owlready2 的 .ancestors() 只走断言 subClassOf;单父重构后
    # 维度类 ⊑ KnowledgeAtom 是经 equivalent_to 蕴含的,断言闭包到不了。
    # 这里把等价公理的命名合取分量也当边,一次算全。
    onto.edu_ancestor_map = _compute_ancestor_map(onto)

    onto._edu_version = VERSION
    return onto


def _conjuncts(expr):
    """展开 And 构造的合取分量(命名类/限制/嵌套 And)。"""
    if hasattr(expr, "Classes"):  # And / Or 构造
        for sub in expr.Classes:
            yield from _conjuncts(sub)
    else:
        yield expr


def _compute_ancestor_map(onto) -> dict[str, set[str]]:
    """named class -> 全部命名祖先(断言 subClassOf ∪ equivalent_to 分量)。"""
    result: dict[str, set[str]] = {}

    def direct_supers(cls) -> set:
        out = set()
        for parent in cls.is_a:
            if isinstance(parent, type):
                out.add(parent)
        for eq in cls.equivalent_to:
            for part in _conjuncts(eq):
                if isinstance(part, type):
                    out.add(part)
        return out

    def ancestors(cls, seen: set[str]) -> set[str]:
        if cls.name in result:
            return result[cls.name]
        if cls.name in seen:
            return set()
        seen.add(cls.name)
        out: set[str] = set()
        for sup in direct_supers(cls):
            out.add(sup.name)
            out |= ancestors(sup, seen)
        result[cls.name] = out
        return out

    for cls in onto.classes():
        ancestors(cls, set())
    return result


# 类的中文标签与一句话说明(构建时写入 zhLabel / rdfs:comment)
_CLASS_LABELS: dict[str, tuple[str, str]] = {
    "KnowledgeAtom": ("知识原子", "教学系统中最小可独立讲授/评测的知识单元。"),
    "KnowledgeDimension": ("知识维度", "Bloom 修订分类知识维度的枚举类。"),
    "CognitiveProcessLevel": ("认知过程层级", "Bloom 修订分类认知过程维度的枚举类。"),
    "FactualKnowledge": ("事实性知识", "由 hasKnowledgeDimension=事实性 定义的性质决定类。"),
    "ConceptualKnowledge": ("概念性知识", "由 hasKnowledgeDimension=概念性 定义。"),
    "ProceduralKnowledge": ("程序性知识", "由 hasKnowledgeDimension=程序性 定义。"),
    "Fact": ("事实", "术语、常数、约定、具体细节。"),
    "Concept": ("概念", "类别及其结构。"),
    "Principle": ("原理", "因果/规律性知识。"),
    "Formula": ("公式", "形式化符号关系。"),
    "Procedure": ("方法", "算法与流程。"),
    "KnowledgeClaim": ("知识断言", "某主体对知识的主张;认识态度独立成轴。"),
    "MisconceptionClaim": ("迷思断言", "必须指明它扭曲哪个正确原子。"),
    "UnverifiedClaim": ("待验证断言", "引用校验未通过的生成内容,禁止静默入库。"),
    "LearnerBelief": ("学习者信念", "学习者持有的、可对可错的知识主张。"),
    "EducationalArtifact": ("教学制品", "知识的载体与教学装置。"),
    "SourceDocument": ("来源文档", "原始 PDF/讲义。"),
    "WikiPage": ("维基页面", "知识/断言/制品的页面载体。"),
    "Example": ("例题制品", "worked example 教学装置。"),
    "Inquiry": ("探究问题", "多视角探究问题。"),
    "LearningObjective": ("学习目标", "对齐 Bloom 认知层级的学习目标。"),
    "LearningPath": ("学习路径", "有序学习步骤。"),
    "Rubric": ("量规", "掌握等级与评分规则。"),
    "Guide": ("学习指引", "导览与支架。"),
    "PathStep": ("路径步骤", "学习路径的步骤节点。"),
    "Learner": ("学习者", "学习者个体。"),
    "MasteryAssertion": ("掌握断言", "学习者×原子 的掌握概率(BKT 输出落点)。"),
    "LearningEvent": ("学习事件", "接触/作答/复习事件。"),
    "ExposureEvent": ("接触事件", "阅读/浏览。"),
    "AttemptEvent": ("作答事件", "评测作答。"),
    "ReviewEvent": ("复习事件", "间隔复习。"),
    "MisconceptionTrace": ("迷思痕迹", "学习者犯下迷思断言的痕迹。"),
    "AssessmentItem": ("评测项", "题目。"),
    "MisconceptionTaxon": ("迷思分类", "错误类型分类。"),
    "MasteredAtom": ("已掌握原子", "定义类:存在 pKnown≥阈值 的掌握断言。"),
    "LearnerStatusAtom": ("学习者状态原子", "组织父类:按学习者掌握状态划分原子(已掌握/就绪/迁移候选),与知识类型轴正交。"),
    "ReadyAtom": ("就绪原子(前沿)", "定义类:未掌握且全部先修已掌握。逐学习者物化视图上求值。"),
    "TransferCandidate": ("迁移候选", "定义类:未掌握但存在已掌握原子迁移到它。"),
}


#: 仅作互逆引用的属性的中文标签(_apply_labels_and_comments 写入 zhLabel)
_INVERSE_PROPERTY_ZH = {
    "hasPrerequisite": "先修包含",
    "receivedTransferFrom": "迁移自",
    "masteredBy": "被掌握断言指向",
}


def _apply_labels_and_comments(onto) -> None:
    # Keep v1's detailed descriptions while adding labels for every class
    # introduced by the v2 TeachingObject taxonomy.  Import lazily to avoid a
    # module cycle during startup.
    from services.ontology_v2 import TEACHING_CLASS_LABELS

    class_labels = {**_CLASS_LABELS, **TEACHING_CLASS_LABELS}
    for name, (zh, comment) in class_labels.items():
        cls = getattr(onto, name, None)
        if cls is None:
            continue
        cls.label = [locstr(name, lang="en")]
        cls.zhLabel = [locstr(zh, lang="zh")]
        cls.comment = [locstr(comment, lang="zh")]
    for spec in RELATION_SPECS:
        prop = getattr(onto, spec.name, None)
        if prop is None:
            continue
        prop.label = [locstr(spec.name, lang="en")]
        prop.zhLabel = [locstr(spec.zh, lang="zh")]
        if spec.rationale:
            prop.comment = [locstr(spec.rationale, lang="zh")]
    for prop_name, zh in _INVERSE_PROPERTY_ZH.items():
        prop = getattr(onto, prop_name, None)
        if prop is not None:
            prop.zhLabel = [locstr(zh, lang="zh")]
    for name, zh, _domain, _py_type in _DATA_PROPERTY_SPECS:
        prop = getattr(onto, name, None)
        if prop is not None:
            prop.zhLabel = [locstr(zh, lang="zh")]


# ---------------------------------------------------------------------------
# 对外注册表 —— 其他模块(生成层/图谱层/推理服务)从这里取常量
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EduOnto:
    """构建结果 + 派生元数据的只读注册表。"""

    onto: object
    version: str = VERSION
    mastery_threshold: Decimal = MASTERY_THRESHOLD
    page_templates: dict[str, tuple[str, str]] = field(
        default_factory=lambda: dict(PAGE_TEMPLATES)
    )
    relation_specs: tuple[RelationSpec, ...] = RELATION_SPECS

    @property
    def knowledge_classes(self) -> list[str]:
        return ["Fact", "Concept", "Principle", "Formula", "Procedure"]

    @property
    def relation_names(self) -> list[str]:
        return [s.name for s in RELATION_SPECS]

    def relation(self, name: str) -> RelationSpec:
        for spec in RELATION_SPECS:
            if spec.name == name:
                return spec
        raise KeyError(name)


_default: EduOnto | None = None


def get_edu_ontology() -> EduOnto:
    """返回默认 world 上的单例本体(进程内共享)。"""
    global _default
    if _default is None:
        _default = EduOnto(onto=build_ontology())
    return _default
