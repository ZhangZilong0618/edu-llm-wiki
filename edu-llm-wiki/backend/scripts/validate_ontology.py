"""用 HermiT 推理器验证 EDU-ONTO 本体的形式性质。

五个场景(每个隔离 World、独立推理):
  1. bare      —— 空 ABox 的 TBox 必须一致(本体自身无矛盾)。
  2. normal    —— 正常 ABox:ReadyAtom / TransferCandidate 自动归类,
                  ContrastRisk SWRL 规则推断 atRiskOfConfusing。
  3. cycle     —— 先修环 → 不一致(prerequisiteOf 反自反 + SWRL 传递规则,
                  环经规则推出 a→a 后被反自反公理抓获,DAG 形式不变量)。
  4. typeclash —— 同一个体既断言 Concept 又断言 Formula → 不一致(互斥公理)。
  5. badtarget —— distorts 指向非知识原子(WikiPage)→ 不一致(值域违反)。

开放世界假设的诚实边界(场景 2 内演示):
  - "迷思未写明 distorts 对象"在 OWA 下推理器不报错(匿名填充者即可满足
    存在约束)。这一项由 validate_misconception_claims() 做 ABox 级校验,
    属于物化/校验层职责,不是描述逻辑能表达的。

用法(在 backend/ 目录下,需要 Java 运行时):
    python3 scripts/validate_ontology.py
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from owlready2 import (  # noqa: E402
    OwlReadyInconsistentOntologyError,
    World,
    sync_reasoner,
)

from services.ontology import MASTERY_THRESHOLD, build_ontology  # noqa: E402
from services.ontology.materialize import materialize_learner_view  # noqa: E402

PASS = "✓"
FAIL = "✗"


def fresh_ontology():
    """隔离 World 上的全新本体实例(场景互不污染)。"""
    return build_ontology(world=World())


def reason(onto):
    """运行 HermiT 并回传推理结果(含 SWRL 规则结论)。

    注意 owlready2 的 ``infer_property_values`` 默认 False:不显式打开,
    HermiT 内部照常应用规则,但**结论不会回传**到 Python 世界。
    """
    return sync_reasoner(onto, infer_property_values=True)


def scenario_bare() -> bool:
    onto = fresh_ontology()
    sync_reasoner(onto)
    print(f"{PASS} 场景1 bare:空 ABox 的 TBox 经 HermiT 一致")
    return True


def scenario_normal() -> bool:
    onto = fresh_ontology()
    with onto:
        # 知识原子:A --先修--> B --先修--> C;A 迁移至 D;E 与 A 易混淆
        a = onto.Concept("atom_carrier")            # 载流子
        b = onto.Formula("atom_ohm_formula")        # 欧姆定律公式
        c = onto.Concept("atom_resistance")         # 电阻
        d = onto.Concept("atom_semiconductor")      # 半导体
        e = onto.Concept("atom_hole")               # 空穴
        a.prerequisiteOf = [b]
        b.prerequisiteOf = [c]
        a.transfersTo = [d]
        a.contrastsWith = [e]

        # 学习者与掌握断言:A 已掌握(pKnown 0.9 ≥ 0.85)
        learner = onto.Learner("learner_li")
        ma = onto.MasteryAssertion("ma_li_A", ofLearner=[learner], ofAtom=[a])
        ma.pKnown = [float(MASTERY_THRESHOLD) + 0.05]

        # 迷思断言 + 学习者痕迹:触发 ContrastRisk SWRL 规则
        mc = onto.MisconceptionClaim("claim_confuse_direction", distorts=[a])
        trace = onto.MisconceptionTrace(
            "trace_li_1", ofLearner=[learner], ofClaim=[mc]
        )

    # 逐学习者物化:未掌握显式化 + 先修传递闭包封闭(OWA 妥协落地)
    mat = materialize_learner_view(onto)
    print(f"   物化: mastered={mat['mastered']} unmastered={mat['unmastered']}")

    reason(onto)

    mastered = {i.name for i in onto.MasteredAtom.instances()}
    ready = {i.name for i in onto.ReadyAtom.instances()}
    transfer = {i.name for i in onto.TransferCandidate.instances()}
    # owlready2 属性访问返回宾语的迭代器(不含主语),按宾集读取
    at_risk = {o.name for o in learner.atRiskOfConfusing}

    print(f"   MasteredAtom      = {sorted(mastered)}")
    print(f"   ReadyAtom         = {sorted(ready)}")
    print(f"   TransferCandidate = {sorted(transfer)}")
    print(f"   atRiskOfConfusing(learner_li) = {sorted(at_risk)}")

    checks = [
        ("A 归类为 MasteredAtom", "atom_carrier" in mastered),
        ("B 归类为 ReadyAtom(先修 A 已掌握)", "atom_ohm_formula" in ready),
        ("C 不在 ReadyAtom(先修 B 未掌握)", "atom_resistance" not in ready),
        ("D 归类为 TransferCandidate(已掌握的 A 迁移至 D)",
         "atom_semiconductor" in transfer),
        ("SWRL 推断 atRiskOfConfusing(学习者, E)",
         "atom_hole" in at_risk),
    ]
    ok = True
    for desc, passed in checks:
        print(f"   {PASS if passed else FAIL} {desc}")
        ok = ok and passed
    return ok


def scenario_cycle() -> bool:
    onto = fresh_ontology()
    with onto:
        x = onto.Concept("atom_x")
        y = onto.Concept("atom_y")
        x.prerequisiteOf = [y]
        y.prerequisiteOf = [x]
    try:
        reason(onto)
    except OwlReadyInconsistentOntologyError:
        print(f"{PASS} 场景3 cycle:先修环被 HermiT 判为不一致(DAG 形式不变量生效)")
        return True
    print(f"{FAIL} 场景3 cycle:含环本体竟然一致,公理失效!")
    return False


def scenario_type_clash() -> bool:
    onto = fresh_ontology()
    with onto:
        rogue = onto.Concept("rogue_atom")
        rogue.is_a.append(onto.Formula)  # 同一个体两种互斥原子类型
    try:
        reason(onto)
    except OwlReadyInconsistentOntologyError:
        print(f"{PASS} 场景4 typeclash:Concept×Formula 互斥公理抓获类型冲突")
        return True
    print(f"{FAIL} 场景4 typeclash:类型冲突未被抓获")
    return False


def scenario_bad_target() -> bool:
    onto = fresh_ontology()
    with onto:
        atom = onto.Concept("atom_a")
        page = onto.WikiPage("page_a")
        mc = onto.MisconceptionClaim("claim_bad", distorts=[page])  # 值域违反
        atom  # noqa: B018 (保持引用)
    try:
        reason(onto)
    except OwlReadyInconsistentOntologyError:
        print(f"{PASS} 场景5 badtarget:distorts 指向 WikiPage 被判不一致(值域公理生效)")
        return True
    print(f"{FAIL} 场景5 badtarget:值域违反未被抓获")
    return False


def validate_misconception_claims(onto) -> list[str]:
    """ABox 级校验:迷思断言必须指明被扭曲对象。

    开放世界下推理器不会报缺 distorts(匿名填充者即可满足存在约束),
    所以"必须指向一个**已知**原子"由这一层强制 —— 这是推理器与
    物化/校验层的分工边界。
    """
    return [
        c.name for c in onto.MisconceptionClaim.instances()
        if not list(c.distorts)
    ]


def main() -> int:
    print(f"HermiT 验证(掌握阈值 = {MASTERY_THRESHOLD})")
    print("-" * 60)
    results = [
        scenario_bare(),
        scenario_normal(),
        scenario_cycle(),
        scenario_type_clash(),
        scenario_bad_target(),
    ]
    # OWA 边界演示:缺 distorts 的迷思由校验层抓
    onto = fresh_ontology()
    with onto:
        onto.MisconceptionClaim("claim_no_target")
    missing = validate_misconception_claims(onto)
    ok_missing = missing == ["claim_no_target"]
    print(f"{PASS if ok_missing else FAIL} 边界演示:缺 distorts 的迷思被校验层标记 "
          f"(推理器不报,OWA 限制): {missing}")
    results.append(ok_missing)

    print("-" * 60)
    if all(results):
        print(f"{PASS} 全部 {len(results)} 项验证通过")
        return 0
    print(f"{FAIL} 有 {results.count(False)} 项验证失败")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
