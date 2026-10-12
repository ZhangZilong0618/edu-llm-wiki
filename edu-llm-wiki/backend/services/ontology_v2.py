"""EDU-ONTO v2 —— 按用户逐条指令从零构建的本体。

架构(2026-10-12):
    owl:Thing
    ├── KnowledgeUnit 知识单元 —— 学什么
    │     Concept 概念 · Fact 事实 · Formula 公式 · Principle 原理
    └── TeachingObject 教学应用对象 —— 谁在学/学得怎样/如何测量/接下来学什么
          ├── 学习者画像与状态  Learner · LearnerProfile · ProfileAssertion
          │                     LearningEvent(DialogueRecord/ExerciseAttempt)
          │                     LearningState · MasteryEvidence
          ├── 习题与评价        Exercise(Option/Target/Rubric) · AssessmentResult
          │                     MasteryUpdateRule · CoverageSnapshot(Record)
          ├── 学习路径规划      LearningPath(Step) · PathAdjustmentRecord
          └── 共用对象          LearningObjective · LearningResource
                                LearningActivity · CognitiveLevel(6 个体)

    对象属性:知识层 14(三层关系体系)+ 逆属性 hasPrerequisite
            + 教学层 26,共 41。
    数据属性:63,其中 5 个带区间约束(0..1)。

约定(沿用 v1.1 踩坑结论):
- 类名/属性名/IRI 用 ASCII 英文;rdfs:label 不放中文(OWLViz 的 DOT
  词法分析器遇 CJK 抛 Lexical error),中文放 zhLabel 注解。
  Protégé 看中文:View → Render by annotation → zhLabel。
- 类/关系/数据属性的描述写入 rdfs:comment(中文),是抽取层与服务层
  的判定依据;受控字符串词表(eventType/coverageStatus/assertionSource
  等)在描述里枚举,暂不用 OWL 个体约束。
- owlready2 陷阱:domain/range 传多个类会序列化为多条 rdfs:domain,
  OWL 语义是交集——必须包成 Or([...]) 单条并集。
- 传递+反自反的组合违反 OWL 2 regularity(非简单属性):传递性由
  SWRL 规则实现,反自反公理抓环,环 = 本体级不一致(v1.1 验证过)。
- evidenceRequired 注解标记"断言需研究数据/原文证据"的关系
  (当前仅 supports/challenges);逐条边的 confidence/context 属
  ABox 元数据,不进 TBox。
- 实体 IRI 即唯一标识:不设 eventId/exerciseId/pathId 之类的
  冗余 id 数据属性,只保留语义版本号。
- 显式 subClassOf owl:Thing 是冗余三元组,构建后清除。
- 互斥公理(AllDisjoint)尚未加入——待用户拍板。

构建/导出(在 backend/ 目录下):
    python3 services/ontology_v2.py
    → ../data/ontology/edu-onto-v2.owl
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from owlready2 import (
    AllDifferent,
    AnnotationProperty,
    ConstrainedDatatype,
    DatatypeProperty,
    FunctionalProperty,
    Imp,
    IrreflexiveProperty,
    locstr,
    ObjectProperty,
    Or,
    SymmetricProperty,
    Thing,
    TransitiveProperty,
    World,
)

BASE_IRI = "https://edu-llm-wiki.org/ontology/edu-onto-v2"


# =========================================================================
# 知识单元层:四个类
# =========================================================================

#: 事实类的描述 —— 抽取层的类型判定依据(定义/形态/判定测试/边界)。
#: 例子全部取自《第01章 原子结构与键合》,已逐条核对原文。
FACT_DESCRIPTION = """\
单点为真的具体陈述：数值、测量值、命名约定、具体个体的具体性质。主语是
具体个体（某元素、某物质、某轨道）或全局约定，不泛化到一类事物；考查方式
是再认/回忆，不是解释或执行。

三种形态：
① 物理常数：e=1.6022×10⁻¹⁹C，质子质量 1.67×10⁻²⁴g，原子直径约 10⁻¹⁰m
  量级，碳链键角 109°28′。
② 具体物质的性质数据：W 熔点 3410℃，全同立构聚丙烯熔点 180℃，天然橡胶
  含 98% 以上的 1,4-顺式聚异戊二烯，铁原子实际电子结构
  1s²2s²2p⁶3s²3p⁶[3d⁶4s²]。
③ 约定与阈值：轨道角动量量子数 l=0,1,2,3,4 依次命名为 s,p,d,f,g；色散力
  可占范德瓦耳斯力的 80%~100%；橡胶交联度超过 30% 即变硬橡胶。

判定测试：内容只对单个个体/单点成立，且考查方式是回忆或再认 → 事实。

边界（与兄弟类逐条对照）：
- 对概念：概念回答“某类别是什么”（金属键＝自由电子与金属正离子的键合），
  可泛化；事实不可泛化，“钨的熔点 3410℃”只对钨成立。
- 对原理：原理是普适因果规律，含“若…则…”结构（电负性差越大→离子键比例
  越高）；事实是无推理结构的单点陈述。“金属导电导热良好”是对一类物质的
  因果论断，属原理不属事实。
- 对公式：公式是含变量的符号关系（2n²，IC≈[1-e^(-0.25(x_A-x_B)²)]×100%）；
  事实只有具体数值。有变量归公式，纯数值归事实。
"""

#: 知识层类名 -> (中文标签, 描述)。描述写入 rdfs:comment;空串 = 尚未定义。
CLASS_LABELS: dict[str, tuple[str, str]] = {
    "KnowledgeUnit": ("知识单元", ""),
    "Concept": ("概念", ""),
    "Fact": ("事实", FACT_DESCRIPTION),
    "Formula": ("公式", ""),
    "Principle": ("原理", ""),
}


# =========================================================================
# 教学应用对象层:24 个类
# =========================================================================

TEACHING_CLASS_LABELS: dict[str, tuple[str, str]] = {
    # — 层根 —
    "TeachingObject": (
        "教学应用对象",
        "教学应用对象层根类：一切服务于教学过程的对象。与知识单元正交——"
        "知识单元回答“学什么”，本层回答谁在学、学得怎样、如何测量、"
        "接下来学什么。",
    ),
    # — 学习者画像与状态 —
    "Learner": (
        "学习者",
        "系统内的学习身份节点，个体 IRI 即用户标识。身份与特性一律经画像"
        "断言表达，不直接挂在学习者上。",
    ),
    "LearnerProfile": (
        "学习者画像",
        "学习者当前画像的容器，由若干画像事实项组成。画像不存总结文本——"
        "结构化断言才可逐条引用、修正与过期。",
    ),
    "ProfileAssertion": (
        "画像事实项",
        "画像中的单项信息。assertionType 维度：goal 学习目标/priorKnowledge "
        "先验知识/interest 兴趣/preference 偏好/difficulty 学习困难/pace "
        "学习节奏。assertionSource：selfReported 学生明示/observed 行为观察"
        "/inferred 模型推断——推断项必须带 fromEvent 证据与 confidence，"
        "不得当作学生明示事实；validTo 已过的断言不参与决策。",
    ),
    "LearningEvent": (
        "学习事件",
        "有教育意义的操作事件流水，追加式记录、不因画像或掌握变化而覆盖。"
        "eventType 受控：read 阅读知识/exerciseStart 开始习题/analysisView "
        "查看解析/review 复习知识/taskComplete 完成任务；对话与作答提交分别"
        "用 DialogueRecord/ExerciseAttempt 子类。网络请求、界面刷新等技术"
        "日志不入事件流。",
    ),
    "DialogueRecord": (
        "对话与思考记录",
        "学生与系统交流的记录：学生原话、想法与推理过程。content 存提炼后"
        "的内容（对话原文在系统对话库），aboutKU 关联讨论涉及的知识单元。",
    ),
    "ExerciseAttempt": (
        "习题作答记录",
        "一次答题提交：作答内容、用时、提示使用。attemptsExercise 指向题目，"
        "hasResult 产生判分结果；答题开始是独立的普通学习事件"
        "（eventType=exerciseStart）。",
    ),
    "LearningState": (
        "学习者知识状态",
        "系统对学习者×知识单元×认知层级掌握程度的当前估计，不代表绝对真值。"
        "只对有证据的(单元,层级)建实例——无实例即“未知”，与“估计为 0”"
        "（有证据显示未掌握）天然区分。masteryLevel 可由 masteryEstimate "
        "阈值派生（≥0.85 熟练）；evidenceCount/lastUpdatedAt 是派生快照字段。",
    ),
    "MasteryEvidence": (
        "掌握证据",
        "支撑或质疑某一掌握判断的具体证据。polarity：positive 支撑/negative "
        "质疑（答错是负向证据）。证据源自评价结果（fromResult）或对话"
        "（fromEvent），至少其一。",
    ),
    # — 习题与评价 —
    "Exercise": (
        "习题",
        "由知识单元内容生成的题目。exerciseType 受控：choice 选择/judgment "
        "判断/calculation 计算/shortAnswer 简答/caseAnalysis 案例分析。"
        "generatedFrom 记录生成时参考的内容，与经考查目标声明的真正测量对象"
        "区分；reviewStatus 生命周期：pending 待审/approved 已审/published "
        "已发布/deprecated 已废弃。个体 IRI 即题目标识。",
    ),
    "ExerciseOption": (
        "习题选项",
        "选择题的候选项。distractorExplanation 干扰项解释——错误选项为何"
        "诱错，是迷思诊断的直接素材。",
    ),
    "ExerciseTarget": (
        "习题考查目标",
        "题目与它真正测量的知识单元×认知层级的关联，带 weight 分值占比。"
        "一题可有多目标，各目标的层级与权重可以不同；不建议把“本题对应"
        "知识单元”存成单一文本字段。",
    ),
    "ScoringRubric": (
        "评分标准",
        "判分规则：scoringRule 规则描述（选择题可空=按选项判分；开放题供"
        "判分模型使用）、maxScore 满分。分项细则暂以文本承载，需要结构化时"
        "再升级。",
    ),
    "AssessmentResult": (
        "评价结果",
        "一次作答经判分后的结果：得分、错误类型、反馈。是作答与掌握证据之间"
        "的中介。",
    ),
    "MasteryUpdateRule": (
        "掌握更新规则",
        "掌握估计更新策略的标识：规则名/参数/版本。学习状态经 computedBy "
        "溯源“这版估计由哪套规则算出”；更新算法本体在服务层实现，不在此"
        "表达。",
    ),
    "KnowledgeCoverageSnapshot": (
        "知识覆盖快照",
        "某时点、某学习者、某学习目标范围内的覆盖总体快照（ofLearner×"
        "forObjective 圈定范围）。快照是物化视图，服务于进度追踪与时点查询，"
        "可从习题/事件/证据重算。",
    ),
    "KnowledgeCoverageRecord": (
        "知识覆盖记录",
        "快照中单个知识单元（×认知层级）的覆盖状态。coverageStatus 四值"
        "严格区分三层覆盖：uncovered 未覆盖/questionGenerated 题库覆盖/"
        "practiced 练习覆盖/evidenceSufficient 证据覆盖——题目生成了但学生"
        "没做，只算题库覆盖，不算学生已被评价。三个计数字段是派生快照。",
    ),
    # — 学习路径规划 —
    "LearningPath": (
        "学习路径",
        "面向某学习者、某学习目标的学习方案，一个版本一个实例。status："
        "draft 草拟/active 进行中/completed 已完成/paused 已暂停/superseded "
        "已废弃。动态调整=生成新版本实例、旧版冻结，调整经 "
        "PathAdjustmentRecord 留痕。规划不得绕过未满足的先修"
        "（prerequisiteOf 在知识层）。",
    ),
    "LearningPathStep": (
        "路径步骤",
        "路径中的一项任务：stepType 受控 learn 学习/practice 练习/review "
        "复习/assess 评价；status：pending 待开始/inProgress 进行中/"
        "completed 已完成/skipped 已跳过。只针对知识单元"
        "（targetsKnowledgeUnit）；具体资源/活动/习题经 usesResource/"
        "prescribesActivity/assignsExercise 布置。",
    ),
    "PathAdjustmentRecord": (
        "路径调整记录",
        "路径为何被调整的显式记录：triggerType 受控 masteryDeficit 掌握不足/"
        "prerequisiteGap 前置缺失/coverageGap 覆盖缺口/objectiveChange 目标"
        "变化；fromVersion/toVersion 指向前后版路径；triggeredBy 溯源到具体"
        "事件/证据/覆盖记录。没有此记录的路径调整不允许发生。",
    ),
    # — 共用对象 —
    "LearningObjective": (
        "学习目标",
        "学习目标节点：objectiveText 描述，targetsKnowledgeUnit 圈定目标覆盖"
        "的知识范围——覆盖快照与路径规划的范围由此确定。",
    ),
    "LearningResource": (
        "学习资源",
        "学习资源节点：resourceRef 引用系统内真实的资源（页面/文档/材料本体"
        "存于系统，此处只存引用）。",
    ),
    "LearningActivity": (
        "学习活动",
        "学习活动节点：activityType 受控 read 阅读/exercise 做题/discuss "
        "讨论/quiz 测验。路径步骤经 prescribesActivity 安排活动。",
    ),
    "CognitiveLevel": (
        "认知层级",
        "Bloom 修订分类认知过程维度的共享词汇表，六个固定个体：识记/理解/"
        "应用/分析/评价/创造。学习状态、习题考查目标、覆盖记录共用。学生"
        "可能识别某概念却不能用于分析——掌握按层级分开维护正是为此。",
    ),
}

#: 认知层级个体:(IRI 短名, 中文标签)
COGNITIVE_LEVELS: tuple[tuple[str, str], ...] = (
    ("lvRemember", "识记"),
    ("lvUnderstand", "理解"),
    ("lvApply", "应用"),
    ("lvAnalyze", "分析"),
    ("lvEvaluate", "评价"),
    ("lvCreate", "创造"),
)


# =========================================================================
# 关系层
# =========================================================================

@dataclass(frozen=True)
class RelationSpec:
    """对象属性规格。domain/range 为空元组 = 不限类型。"""

    name: str
    zh: str
    domain: tuple[str, ...]
    range: tuple[str, ...]
    transitive: bool = False
    symmetric: bool = False
    irreflexive: bool = False
    functional: bool = False
    inverse_of: str | None = None
    evidence_required: bool = False
    description: str = ""


#: 知识层 14 个关系(三层关系体系)。
#: 例子优先取自《第01章 原子结构与键合》,研究型关系辅以教育学示例。
RELATION_SPECS: tuple[RelationSpec, ...] = (
    # — 结构关系:组织知识结构与学习路径 —
    RelationSpec(
        "isA", "属于", ("Concept",), ("Concept",),
        transitive=True, irreflexive=True,
        description=(
            "类型归属：A 是 B 的一种。判据：陈述可改写为“A 是一种 B”。"
            "例：金属键 isA 化学键；形成性评价 isA 教育评价。"
            "与 partOf 互斥使用：A 是 B 的一部分（如近程结构之于链结构）时"
            "用 partOf，不用 isA。"
        ),
    ),
    RelationSpec(
        "partOf", "部分于", ("Concept",), ("Concept",),
        transitive=True, irreflexive=True,
        description=(
            "组成：A 是 B 的组成部件或方面。判据：陈述可改写为"
            "“A 是 B 的一部分”。例：近程结构 partOf 链结构；高分子结构"
            "包含链结构与聚集态结构；教学目标 partOf 教学设计。"
            "与 isA 区分：金属键是一种化学键（isA），不是化学键的一部分。"
        ),
    ),
    RelationSpec(
        "prerequisiteOf", "先修于",
        ("Concept", "Formula", "Principle"),
        ("Concept", "Formula", "Principle"),
        transitive=True, irreflexive=True, inverse_of="hasPrerequisite",
        description=(
            "前置知识：不理解 A 就无法理解 B。只录直接前置，间接前置由"
            "传递闭包推导，不重复录入。例：原子结构 prerequisiteOf 原子间"
            "键合；认知发展 prerequisiteOf 最近发展区。方向必须唯一"
            "（A 先修于 B 时不得同时 B 先修于 A），有向环即本体不一致；"
            "事实不作为先修节点。"
        ),
    ),
    # — 语义与证据关系:连接理论、概念与实证证据 —
    RelationSpec(
        "explains", "解释", ("Principle",), ("Concept", "Fact"),
        description=(
            "原理解释目标概念/事实的机制或成因。例：“未填满的 3d 能级使铁"
            "产生磁性”这一原理 explains 铁的磁性行为；建构主义学习原理"
            "explains 主动建构知识。边界：不得退化为一般性相关——原理必须"
            "提供机制性解释，仅“两者有关联”不构成 explains。"
        ),
    ),
    RelationSpec(
        "appliesTo", "适用于", ("Principle",), ("Concept", "Fact"),
        description=(
            "原理适用的情境、概念或实践领域。例：能量最低原理 appliesTo"
            " 核外电子排布；建构主义原理 appliesTo 探究式教学设计。"
            "与 explains 区分：appliesTo 表“在何处可用”，不要求解释机制。"
        ),
    ),
    RelationSpec(
        "exemplifies", "例证", ("Fact",), ("Concept", "Principle"),
        description=(
            "事实是概念/原理的具体表现或实例。例：“氢分子的结合是最典型的"
            "共价键”这一事实 exemplifies 共价键；某项反馈干预研究"
            " exemplifies 形成性评价。边界：例证只表明具体表现，不承担证明"
            "理论主张的职能——要表达证据支持用 supports。"
        ),
    ),
    RelationSpec(
        "supports", "支持", ("Fact",), ("Principle",),
        evidence_required=True,
        description=(
            "事实为原理提供支持性证据。例：某研究记录的反馈干预与前后测"
            "成绩变化 supports“及时且有针对性的反馈有助于改善学习”。"
            "注意：单一研究支持不等于原理普遍成立，研究对象、样本、情境与"
            "证据强度应记录在事实节点属性中；断言本关系需要研究数据级证据。"
        ),
    ),
    RelationSpec(
        "challenges", "质疑", ("Fact",), ("Principle",),
        evidence_required=True,
        description=(
            "事实对原理的适用范围或某项预测提出挑战。例：与某原理预测相悖"
            "的实证发现 challenges 该原理的适用边界。使用须谨慎：要有明确的"
            "冲突证据，“看似不一致”不构成 challenges；断言本关系需要研究"
            "数据级证据。"
        ),
    ),
    # — 计算与形式化关系:连接抽象知识、量化模型与计算结果 —
    RelationSpec(
        "operationalizedBy", "操作化为", ("Concept",), ("Formula",),
        description=(
            "抽象概念经公式转化为可计算指标。例：数均相对分子质量"
            " operationalizedBy M̄ₙ=ΣxᵢMᵢ；学习增益 operationalizedBy"
            " 标准化增益公式 g=(后测-前测)/(满分-前测)。"
        ),
    ),
    RelationSpec(
        "usesVariable", "使用变量", ("Formula",), ("Concept",),
        description=(
            "公式中的变量对应某个概念或测量指标。例："
            "IC≈[1-e^(-0.25(x_A-x_B)²)]×100% usesVariable 电负性；"
            "标准化增益公式 usesVariable 前测成绩。"
        ),
    ),
    RelationSpec(
        "formalizes", "形式化表达", ("Formula",), ("Principle",),
        description=(
            "公式将原理表达为定量关系。例：2n² formalizes 泡利不相容原理的"
            "壳层容纳上限；IC 公式 formalizes“电负性差越大离子键比例越高”。"
            "边界：并非所有原理都对应公式（教育哲学、学习理论中大量原理无法"
            "形式化为单个公式），不得默认一一对应。"
        ),
    ),
    RelationSpec(
        "derivedFrom", "推导自", ("Formula",), ("Formula", "Principle"),
        transitive=True, irreflexive=True,
        description=(
            "公式的推导依赖另一公式或某原理。例：高斯链均方末端距公式"
            " derivedFrom 自由旋转链公式（后者又 derivedFrom 自由结合链"
            "公式）；聚合度 n=M̄ₙ/m̄ derivedFrom 数均分子质量的定义。"
        ),
    ),
    RelationSpec(
        "providesInputTo", "提供输入", ("Fact",), ("Formula",),
        description=(
            "观测值、测量值或已知条件作为公式的输入。例：Na 与 Cl 的电负性"
            "差值（事实）providesInputTo IC 公式；某班前测成绩记录"
            " providesInputTo 标准化增益公式。"
        ),
    ),
    RelationSpec(
        "calculates", "计算得到", ("Formula",), ("Fact",),
        description=(
            "公式对具体输入计算出的结果事实。例：IC 公式 calculates"
            "“NaCl 的离子键比例约 71%”；标准化增益公式 calculates 该班的"
            "标准化学习增益。"
        ),
    ),
)

#: 教学应用对象层 26 个关系。
TEACHING_RELATION_SPECS: tuple[RelationSpec, ...] = (
    # — 学习者画像与状态 —
    RelationSpec(
        "hasProfile", "画像为", ("Learner",), ("LearnerProfile",),
        description=(
            "学习者当前持有的画像。画像重算时新建 LearnerProfile 实例并"
            "指向它，旧画像留档。"
        ),
    ),
    RelationSpec(
        "hasAssertion", "含画像项", ("LearnerProfile",), ("ProfileAssertion",),
        description=(
            "画像由若干画像事实项组成；inferred 来源的断言必须同时挂"
            " fromEvent 证据。"
        ),
    ),
    RelationSpec(
        "ofLearner", "属学习者",
        ("LearningEvent", "LearningState", "LearningPath",
         "KnowledgeCoverageSnapshot"),
        ("Learner",),
        description=(
            "学习事件/学习状态/学习路径/覆盖快照归属的学习者。"
            "参考稿的 forLearner 与本关系语义相同,已合并。"
        ),
    ),
    RelationSpec(
        "aboutKU", "关于知识单元", ("LearningEvent", "MasteryEvidence"),
        ("KnowledgeUnit",),
        description=(
            "学习事件（阅读/复习/对话）与掌握证据涉及的知识单元。作答事件"
            "不直接挂——经 attemptsExercise→考查目标派生。"
        ),
    ),
    RelationSpec(
        "attemptsExercise", "作答于", ("ExerciseAttempt",), ("Exercise",),
        description="作答记录针对的习题。",
    ),
    RelationSpec(
        "hasResult", "产生结果", ("ExerciseAttempt",), ("AssessmentResult",),
        description="作答经判分产生的评价结果。",
    ),
    RelationSpec(
        "hasCognitiveLevel", "认知层级为",
        ("LearningState", "ExerciseTarget"), ("CognitiveLevel",),
        functional=True,
        description=(
            "学习状态/考查目标对应的认知层级（识记…创造六选一）。函数属性："
            "一个状态/一个目标恰一个层级；配合六个层级个体 AllDifferent，"
            "标两个不同层级即不一致。"
        ),
    ),
    RelationSpec(
        "evidencedBy", "证据为", ("LearningState",), ("MasteryEvidence",),
        description="支撑该学习状态估计的掌握证据（多值）。",
    ),
    RelationSpec(
        "fromResult", "源自结果", ("MasteryEvidence",), ("AssessmentResult",),
        description="掌握证据源自哪次评价结果。",
    ),
    RelationSpec(
        "fromEvent", "源自事件",
        ("MasteryEvidence", "ProfileAssertion"), ("LearningEvent",),
        description=(
            "掌握证据/画像断言追溯到哪次学习事件（对话证据、行为观察）。"
            "评价类证据经 fromResult→hasResult 链追溯，不必再挂本关系。"
        ),
    ),
    RelationSpec(
        "computedBy", "依据规则", ("LearningState",), ("MasteryUpdateRule",),
        description="该状态估计由哪套掌握更新规则计算（版本溯源）。",
    ),
    # — 习题与评价 —
    RelationSpec(
        "generatedFrom", "生成自", ("Exercise",), ("KnowledgeUnit",),
        description=(
            "题目生成时参考了哪些知识单元——不等于真正测量什么（那由考查"
            "目标声明）。例：反馈策略案例题参考了形成性评价概念，但测量的"
            "是有效反馈原理的运用。"
        ),
    ),
    RelationSpec(
        "hasTarget", "含考查目标", ("Exercise",), ("ExerciseTarget",),
        description="题目具有的考查目标（一题多目标,各有层级与权重）。",
    ),
    RelationSpec(
        "targetsKnowledgeUnit", "针对知识单元",
        ("ExerciseTarget", "LearningPathStep", "LearningObjective"),
        ("KnowledgeUnit",),
        description=(
            "考查目标实际测量的知识单元（单值,由抽取层保证）；路径步骤重点"
            "学习的知识单元；学习目标圈定的知识范围（多值）。"
        ),
    ),
    RelationSpec(
        "hasOption", "含选项", ("Exercise",), ("ExerciseOption",),
        description="选择题的候选项。",
    ),
    RelationSpec(
        "hasRubric", "用评分标准", ("Exercise",), ("ScoringRubric",),
        description="题目使用的判分规则。",
    ),
    RelationSpec(
        "hasCoverageRecord", "含覆盖记录",
        ("KnowledgeCoverageSnapshot",), ("KnowledgeCoverageRecord",),
        description="快照包含的各知识单元覆盖记录。",
    ),
    RelationSpec(
        "hasCoveredLevel", "已覆盖层级",
        ("KnowledgeCoverageRecord",), ("CognitiveLevel",),
        description="该单元已被出题/练习覆盖到的认知层级（多值）。",
    ),
    # — 学习路径规划 —
    RelationSpec(
        "forObjective", "针对学习目标",
        ("LearningPath", "KnowledgeCoverageSnapshot"),
        ("LearningObjective",),
        description="学习路径要实现的学习目标；覆盖快照统计的范围。",
    ),
    RelationSpec(
        "hasStep", "含步骤", ("LearningPath",), ("LearningPathStep",),
        description="路径包含的步骤。",
    ),
    RelationSpec(
        "usesResource", "用资源", ("LearningPathStep",), ("LearningResource",),
        description="该步骤使用的材料。",
    ),
    RelationSpec(
        "prescribesActivity", "排活动",
        ("LearningPathStep",), ("LearningActivity",),
        description="该步骤安排学生完成的活动。",
    ),
    RelationSpec(
        "assignsExercise", "布习题", ("LearningPathStep",), ("Exercise",),
        description="该步骤布置的具体习题。",
    ),
    RelationSpec(
        "triggeredBy", "触发于", ("PathAdjustmentRecord",),
        ("LearningEvent", "MasteryEvidence", "KnowledgeCoverageRecord"),
        description="路径调整由哪个学习事件/掌握证据/覆盖记录触发。",
    ),
    RelationSpec(
        "fromVersion", "原版本",
        ("PathAdjustmentRecord",), ("LearningPath",),
        description="调整前的路径版本（取代参考稿的 previousVersion 数据属性）。",
    ),
    RelationSpec(
        "toVersion", "新版本",
        ("PathAdjustmentRecord",), ("LearningPath",),
        description="调整产生的新路径版本（取代参考稿的 newVersion/recordsAdjustmentOf）。",
    ),
)

#: 仅作互逆引用的属性的中文标签
_INVERSE_PROPERTY_ZH = {"hasPrerequisite": "先修包含"}


# =========================================================================
# 数据属性层
# =========================================================================

@dataclass(frozen=True)
class DataPropertySpec:
    """数据属性规格。给出 min/max 即施加数据区间约束。"""

    name: str
    zh: str
    domain: tuple[str, ...]
    dtype: object
    description: str = ""
    min_value: float | None = None
    max_value: float | None = None


#: 63 个数据属性。受控字符串词表在描述里枚举。
DATA_PROPERTY_SPECS: tuple[DataPropertySpec, ...] = (
    # — 学习者画像与状态 —
    DataPropertySpec("profileVersion", "画像版本", ("LearnerProfile",), int,
                     "画像重算的递增版本号。"),
    DataPropertySpec("assertionType", "画像维度", ("ProfileAssertion",), str,
                     "受控：goal 目标/priorKnowledge 先验知识/interest 兴趣/"
                     "preference 偏好/difficulty 困难/pace 节奏。"),
    DataPropertySpec("assertionValue", "画像内容", ("ProfileAssertion",), str,
                     "断言的具体内容,如“偏好先看例子再看抽象定义”。"),
    DataPropertySpec("assertionSource", "画像来源", ("ProfileAssertion",), str,
                     "受控：selfReported 学生明示/observed 行为观察/inferred "
                     "模型推断。推断项必须带 fromEvent 证据。"),
    DataPropertySpec("confidence", "置信度", ("ProfileAssertion",), float,
                     "断言置信度 0..1,推断项必填。", 0.0, 1.0),
    DataPropertySpec("validFrom", "生效自", ("ProfileAssertion",),
                     datetime, "断言生效时间。"),
    DataPropertySpec("validTo", "生效至", ("ProfileAssertion",),
                     datetime,
                     "断言失效时间,过期断言不参与决策。"),
    DataPropertySpec("confirmationStatus", "确认状态", ("ProfileAssertion",), str,
                     "受控：unconfirmed 未确认/confirmed 学生已确认/"
                     "corrected 学生更正。"),
    DataPropertySpec("eventType", "事件类型", ("LearningEvent",), str,
                     "受控：read 阅读知识/exerciseStart 开始习题/analysisView "
                     "查看解析/review 复习知识/taskComplete 完成任务。对话与"
                     "作答提交用 DialogueRecord/ExerciseAttempt 类,不占此值。"),
    DataPropertySpec("occurredAt", "发生于", ("LearningEvent",),
                     datetime, "事件发生时间。"),
    DataPropertySpec("sessionId", "会话", ("LearningEvent",), str,
                     "所属会话标识。"),
    DataPropertySpec("duration", "时长", ("LearningEvent",), float,
                     "事件持续时长（秒）。"),
    DataPropertySpec("actionResult", "行为结果", ("LearningEvent",), str,
                     "行为结果,如阅读是否完成、查看解析后是否重做。"),
    DataPropertySpec("content", "内容", ("DialogueRecord",), str,
                     "对话中学生的原话/想法/推理过程（提炼后）。"),
    DataPropertySpec("submittedAnswer", "作答内容", ("ExerciseAttempt",), str,
                     "学生提交的作答内容。"),
    DataPropertySpec("timeSpent", "用时", ("ExerciseAttempt",), float,
                     "答题用时（秒）。"),
    DataPropertySpec("hintsUsed", "提示使用", ("ExerciseAttempt",), int,
                     "答题过程中使用提示的次数。"),
    DataPropertySpec("masteryEstimate", "掌握估计", ("LearningState",), float,
                     "掌握程度估计 0..1。未知=无状态实例,不是 0。", 0.0, 1.0),
    DataPropertySpec("masteryLevel", "掌握等级", ("LearningState",), str,
                     "受控：initial 初步掌握/developing 发展中/proficient "
                     "熟练。可由估计阈值派生(≥0.85 熟练)。"),
    DataPropertySpec("estimateConfidence", "估计置信度", ("LearningState",),
                     float, "掌握估计的可信程度 0..1。", 0.0, 1.0),
    DataPropertySpec("evidenceCount", "证据数",
                     ("LearningState", "KnowledgeCoverageRecord"), int,
                     "派生快照：支撑状态的证据数/覆盖记录的有效证据数。"),
    DataPropertySpec("lastUpdatedAt", "最近更新", ("LearningState",),
                     datetime,
                     "状态最近更新时间（派生快照）。"),
    DataPropertySpec("evidenceType", "证据类型", ("MasteryEvidence",), str,
                     "受控：correctness 作答正确性/scoreItem 分项得分/"
                     "explanation 解释质量/hintUse 提示依赖。"),
    DataPropertySpec("polarity", "证据极性", ("MasteryEvidence",), str,
                     "受控：positive 支撑/negative 质疑。答错是负向证据。"),
    DataPropertySpec("weight", "权重",
                     ("MasteryEvidence", "ExerciseTarget"), float,
                     "权重 0..1：证据强度（MasteryEvidence）或考查分值占比"
                     "（ExerciseTarget）。", 0.0, 1.0),
    # — 习题与评价 —
    DataPropertySpec("stem", "题干", ("Exercise",), str, "题干文本。"),
    DataPropertySpec("exerciseType", "题型", ("Exercise",), str,
                     "受控：choice 选择/judgment 判断/calculation 计算/"
                     "shortAnswer 简答/caseAnalysis 案例分析。"),
    DataPropertySpec("answerKey", "答案", ("Exercise",), str,
                     "标准答案或参考答案。"),
    DataPropertySpec("analysis", "解析", ("Exercise",), str, "答案解析。"),
    DataPropertySpec("difficulty", "难度", ("Exercise",), float,
                     "难度估计 0..1（0 最易）。", 0.0, 1.0),
    DataPropertySpec("generationMethod", "生成方式", ("Exercise",), str,
                     "规则生成/模板生成/大模型生成等。"),
    DataPropertySpec("generationReason", "生成原因", ("Exercise",), str,
                     "本题的生成原因,如填补覆盖缺口。"),
    DataPropertySpec("version", "版本",
                     ("Exercise", "MasteryUpdateRule", "LearningPath"), int,
                     "语义版本号：习题/更新规则/路径各自的版本。"),
    DataPropertySpec("reviewStatus", "审核状态", ("Exercise",), str,
                     "受控：pending 待审/approved 已审/published 已发布/"
                     "deprecated 已废弃。"),
    DataPropertySpec("optionContent", "选项内容", ("ExerciseOption",), str,
                     "选项文本。"),
    DataPropertySpec("isCorrect", "选项正确", ("ExerciseOption",), bool,
                     "该选项是否为正确答案。"),
    DataPropertySpec("distractorExplanation", "干扰项解释",
                     ("ExerciseOption",), str,
                     "干扰项为何诱错的解释——迷思诊断素材。"),
    DataPropertySpec("scoringRule", "判分规则", ("ScoringRubric",), str,
                     "判分规则描述;选择题可空（按选项判分）,开放题供判分"
                     "模型使用。"),
    DataPropertySpec("maxScore", "满分", ("ScoringRubric",), float, "满分。"),
    DataPropertySpec("score", "得分", ("AssessmentResult",), float,
                     "本次作答得分。"),
    DataPropertySpec("errorType", "错误类型", ("AssessmentResult",), str,
                     "错误类型,如概念混淆、计算失误。"),
    DataPropertySpec("feedback", "反馈", ("AssessmentResult",), str,
                     "给学生的反馈。"),
    DataPropertySpec("ruleName", "规则名", ("MasteryUpdateRule",), str,
                     "更新规则名,如 bkt-standard。"),
    DataPropertySpec("ruleParams", "规则参数", ("MasteryUpdateRule",), str,
                     "规则参数（文本/JSON）。"),
    DataPropertySpec("takenAt", "快照时间", ("KnowledgeCoverageSnapshot",),
                     datetime, "快照时点。"),
    DataPropertySpec("coverageStatus", "覆盖状态",
                     ("KnowledgeCoverageRecord",), str,
                     "受控：uncovered 未覆盖/questionGenerated 题库覆盖/"
                     "practiced 练习覆盖/evidenceSufficient 证据覆盖。"
                     "三层严格区分。"),
    DataPropertySpec("generatedQuestionCount", "题目数",
                     ("KnowledgeCoverageRecord",), int,
                     "该单元已生成的题目数（派生快照）。"),
    DataPropertySpec("attemptCount", "作答数",
                     ("KnowledgeCoverageRecord",), int,
                     "学生实际作答次数（派生快照）。"),
    DataPropertySpec("coverageGapReason", "缺口原因",
                     ("KnowledgeCoverageRecord",), str,
                     "仍未覆盖或证据不足的原因。"),
    # — 学习路径规划 —
    DataPropertySpec("status", "状态",
                     ("LearningPath", "LearningPathStep"), str,
                     "路径：draft 草拟/active 进行中/completed 已完成/paused "
                     "已暂停/superseded 已废弃；步骤：pending 待开始/"
                     "inProgress 进行中/completed 已完成/skipped 已跳过。"),
    DataPropertySpec("planningStrategy", "规划策略", ("LearningPath",), str,
                     "路径生成策略标识。"),
    DataPropertySpec("createdAt", "创建于", ("LearningPath",),
                     datetime, "路径创建时间。"),
    DataPropertySpec("updatedAt", "更新于", ("LearningPath",),
                     datetime, "路径最近更新时间。"),
    DataPropertySpec("stepType", "步骤类型", ("LearningPathStep",), str,
                     "受控：learn 学习/practice 练习/review 复习/assess 评价。"),
    DataPropertySpec("sequenceIndex", "步骤序", ("LearningPathStep",), int,
                     "步骤的建议顺序号。"),
    DataPropertySpec("decisionCondition", "触发条件", ("LearningPathStep",), str,
                     "分支或后续步骤的触发条件。"),
    DataPropertySpec("expectedOutcome", "预期结果", ("LearningPathStep",), str,
                     "希望该步骤达到的学习结果。"),
    DataPropertySpec("triggerType", "触发类型", ("PathAdjustmentRecord",), str,
                     "受控：masteryDeficit 掌握不足/prerequisiteGap 前置缺失/"
                     "coverageGap 覆盖缺口/objectiveChange 目标变化。"),
    DataPropertySpec("reason", "调整原因", ("PathAdjustmentRecord",), str,
                     "路径调整原因。"),
    DataPropertySpec("adjustedAt", "调整于", ("PathAdjustmentRecord",),
                     datetime, "调整时间。"),
    # — 共用对象 —
    DataPropertySpec("objectiveText", "目标描述", ("LearningObjective",), str,
                     "学习目标描述。"),
    DataPropertySpec("resourceRef", "资源引用", ("LearningResource",), str,
                     "系统内资源的引用（路径/URI）。"),
    DataPropertySpec("activityType", "活动类型", ("LearningActivity",), str,
                     "受控：read 阅读/exercise 做题/discuss 讨论/quiz 测验。"),
)


# =========================================================================
# 构建函数
# =========================================================================

def build_ontology(*, world: World | None = None):
    """程序化构建 v2 TBox,返回 owlready2 ontology 对象。

    传入隔离的 ``World`` 可获得相互独立的本体实例;幂等。
    """
    onto = (world or World()).get_ontology(BASE_IRI)
    if list(onto.classes()):  # 已构建(classes() 是生成器,不能直接作真值)
        return onto

    # ---- 类:知识单元层 ----
    with onto:
        class KnowledgeUnit(Thing):
            pass

        class Concept(KnowledgeUnit):
            pass

        class Fact(KnowledgeUnit):
            pass

        class Formula(KnowledgeUnit):
            pass

        class Principle(KnowledgeUnit):
            pass

    # ---- 类:教学应用对象层 ----
    with onto:
        class TeachingObject(Thing):
            pass

        class Learner(TeachingObject):
            pass

        class LearnerProfile(TeachingObject):
            pass

        class ProfileAssertion(TeachingObject):
            pass

        class LearningEvent(TeachingObject):
            pass

        class DialogueRecord(LearningEvent):
            pass

        class ExerciseAttempt(LearningEvent):
            pass

        class LearningState(TeachingObject):
            pass

        class MasteryEvidence(TeachingObject):
            pass

        class Exercise(TeachingObject):
            pass

        class ExerciseOption(TeachingObject):
            pass

        class ExerciseTarget(TeachingObject):
            pass

        class ScoringRubric(TeachingObject):
            pass

        class AssessmentResult(TeachingObject):
            pass

        class MasteryUpdateRule(TeachingObject):
            pass

        class KnowledgeCoverageSnapshot(TeachingObject):
            pass

        class KnowledgeCoverageRecord(TeachingObject):
            pass

        class LearningPath(TeachingObject):
            pass

        class LearningPathStep(TeachingObject):
            pass

        class PathAdjustmentRecord(TeachingObject):
            pass

        class LearningObjective(TeachingObject):
            pass

        class LearningResource(TeachingObject):
            pass

        class LearningActivity(TeachingObject):
            pass

        class CognitiveLevel(TeachingObject):
            pass

        class zhLabel(AnnotationProperty):
            pass

        class evidenceRequired(AnnotationProperty):
            pass

    classes = {c.__name__: c for c in onto.classes()}

    # ---- 对象属性:知识层 14 + 教学层 26 ----
    all_relation_specs = (*RELATION_SPECS, *TEACHING_RELATION_SPECS)
    with onto:
        # 先建仅作互逆引用的属性,specs 循环里的 inverse_property 才能引用到
        has_prereq = type("hasPrerequisite", (ObjectProperty,), {})
        if not hasattr(onto, "hasPrerequisite"):
            setattr(onto, "hasPrerequisite", has_prereq)
        has_prereq.label = [locstr("hasPrerequisite", lang="en")]
        has_prereq.zhLabel = [locstr(_INVERSE_PROPERTY_ZH["hasPrerequisite"],
                                     lang="zh")]

        for spec in all_relation_specs:
            # domain/range 多类必须包 Or([...]):owlready2 把 [A,B] 序列化
            # 为两条 rdfs:domain,OWL 语义是交集,互斥类会推成空类
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
            if spec.functional:
                prop.is_a.append(FunctionalProperty)
            if spec.symmetric:
                prop.is_a.append(SymmetricProperty)
            if spec.irreflexive:
                prop.is_a.append(IrreflexiveProperty)
            # 传递+反自反不能同时声明(OWL 2 regularity):这四个属性
            # (isA/partOf/prerequisiteOf/derivedFrom)的传递闭包由下方
            # SWRL 规则实现;纯传递(无反自反)才直接声明 TransitiveProperty
            if spec.transitive and not spec.irreflexive:
                prop.is_a.append(TransitiveProperty)

        # SWRL 传递闭包规则:环 a→b→a 经规则推出 a→a,被反自反公理抓获
        for spec in all_relation_specs:
            if not (spec.transitive and spec.irreflexive):
                continue
            rule = Imp()
            rule.set_as_rule(
                f"{spec.name}(?a, ?b), {spec.name}(?b, ?c) "
                f"-> {spec.name}(?a, ?c)"
            )
            rule.label = [locstr(f"{spec.zh}传递闭包规则", lang="zh")]

        # 关系标签 / 描述 / 证据标记
        for spec in all_relation_specs:
            prop = getattr(onto, spec.name)
            prop.label = [locstr(spec.name, lang="en")]
            prop.zhLabel = [locstr(spec.zh, lang="zh")]
            prop.comment = [locstr(spec.description, lang="zh")]
            prop.evidenceRequired = [spec.evidence_required]

    # ---- 数据属性 ----
    with onto:
        for spec in DATA_PROPERTY_SPECS:
            ents = [classes[n] for n in spec.domain]
            domain = ents if len(ents) == 1 else [Or(ents)]
            if spec.min_value is not None:
                rng = ConstrainedDatatype(
                    spec.dtype, min_inclusive=spec.min_value,
                    max_inclusive=spec.max_value,
                )
            else:
                rng = spec.dtype
            dprop = type(spec.name, (DatatypeProperty,),
                         {"domain": domain, "range": [rng]})
            if not hasattr(onto, spec.name):
                setattr(onto, spec.name, dprop)
            dprop.label = [locstr(spec.name, lang="en")]
            dprop.zhLabel = [locstr(spec.zh, lang="zh")]
            if spec.description:
                dprop.comment = [locstr(spec.description, lang="zh")]

    # ---- 认知层级个体 ----
    with onto:
        level_individuals = [
            classes["CognitiveLevel"](ind_name)
            for ind_name, _zh in COGNITIVE_LEVELS
        ]
        for ind, (_name, zh) in zip(level_individuals, COGNITIVE_LEVELS):
            ind.zhLabel = [locstr(zh, lang="zh")]
        # 配合 hasCognitiveLevel 函数属性:同一状态标两个不同层级即不一致
        AllDifferent(level_individuals)

    # ---- 类标签与描述 ----
    all_class_labels = {**CLASS_LABELS, **TEACHING_CLASS_LABELS}
    for name, (zh, description) in all_class_labels.items():
        cls = getattr(onto, name)
        cls.zhLabel = [locstr(zh, lang="zh")]
        if description:
            cls.comment = [locstr(description, lang="zh")]

    # `class X(Thing)` 的 Python 继承会字面生成 subClassOf owl:Thing
    # 三元组;OWL 中任何类都隐含 ⊑ Thing,显式声明是纯冗余。
    for root_name in ("KnowledgeUnit", "TeachingObject"):
        root = getattr(onto, root_name)
        if Thing in root.is_a:
            root.is_a.remove(Thing)

    return onto


def print_tree(onto) -> None:
    """打印断言的类层次(Protégé 断言树同构)。"""

    def walk(cls, prefix):
        subs = sorted(cls.subclasses(), key=lambda c: c.name)
        for i, sub in enumerate(subs):
            last = i == len(subs) - 1
            zh = sub.zhLabel[0] if sub.zhLabel else ""
            print(f"{prefix}{'└── ' if last else '├── '}{sub.name} {zh}")
            walk(sub, prefix + ("    " if last else "│   "))

    print("owl:Thing")
    roots = [onto.KnowledgeUnit, onto.TeachingObject]
    for i, root in enumerate(roots):
        last = i == len(roots) - 1
        zh = root.zhLabel[0] if root.zhLabel else ""
        print(f"{'└── ' if last else '├── '}{root.name} {zh}")
        walk(root, "    " if last else "│   ")


if __name__ == "__main__":
    onto = build_ontology()
    output = Path(__file__).resolve().parents[2] / "data" / "ontology" / "edu-onto-v2.owl"
    output.parent.mkdir(parents=True, exist_ok=True)
    onto.save(file=str(output))
    n_classes = len(list(onto.classes()))
    n_oprops = len(list(onto.object_properties()))
    n_dprops = len(list(onto.data_properties()))
    n_inds = len(list(onto.individuals()))
    print(f"EDU-ONTO v2  <{BASE_IRI}>")
    print(f"classes={n_classes}  object_properties={n_oprops}  "
          f"data_properties={n_dprops}  individuals={n_inds}")
    print_tree(onto)
    print()
    for spec in (*RELATION_SPECS, *TEACHING_RELATION_SPECS):
        flags = []
        if spec.transitive:
            flags.append("传递(SWRL)" if spec.irreflexive else "传递")
        if spec.symmetric:
            flags.append("对称")
        if spec.irreflexive:
            flags.append("反自反")
        if spec.functional:
            flags.append("函数")
        if spec.inverse_of:
            flags.append(f"逆:{spec.inverse_of}")
        if spec.evidence_required:
            flags.append("需证据")
        sig = f"{'|'.join(spec.domain) or '任意'} → {'|'.join(spec.range) or '任意'}"
        print(f"  {spec.name:20s} {spec.zh:8s} {sig:52s} {' '.join(flags)}")
    print(f"-> {output}  ({output.stat().st_size:,} bytes)")
