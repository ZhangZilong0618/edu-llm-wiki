"""本体关系抽取 —— 导入管线 Stage 1b。

从 Stage 1a 的原子清单抽取知识单元之间的关系。关系词表、方向约束
(domain/range)、判定标准全部来自 services/ontology_v2.py 的
RELATION_SPECS —— 单一事实来源,与类型抽取从 CLASS_LABELS 渲染
同构:本体关系定义更新,抽取标准即更新。

产出经校验的关系(关系名/域值域类型/自环/去重),持久化为
data/projects/{pid}/relations.json;图引擎构图时把它们作为权威边
(origin="ontology")合并进图谱。

环的处理:按用户指示**标记保留**——四个传递关系(prerequisiteOf/
isA/partOf/derivesFrom)的环经可达性检测打 cyclic 标记,不丢弃,
供观察。本体 TBox 的形式校验(SWRL 传递闭包 + 反自反,DAG 不变量)
属 HermiT 审计层,不在热路径。

重跑入口:run_relation_extraction 接受任意原子清单;已导入的项目
用 atoms_from_pages(project_id) 从现有页面重建清单。
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path

from config import settings
from services.extraction import load_llm_json
from services.llm_client import chat_complete
from services.ontology_v2 import RELATION_SPECS

# Relation extraction is enrichment only.  It must not hold an import open
# when the configured model is unavailable; the deterministic graph rebuild
# can continue with zero candidate relations.
LLM_RELATION_TIMEOUT_SECONDS = 15.0

#: 类名 -> 中文(RELATION_SPECS 的 domain/range 用类名)
_CLASS_ZH = {"Concept": "概念", "Fact": "事实", "Formula": "公式", "Principle": "原理"}

#: 页面类型 -> 本体类名(atoms_from_pages 映射用)
_PAGE_TYPE_TO_CLASS = {
    "concept": "Concept",
    "fact": "Fact",
    "formula": "Formula",
    "principle": "Principle",
}

#: 传递关系:环检测标记范围(与本体 SWRL 传递闭包规则对应的四个)
_TRANSITIVE_RELATIONS = ("prerequisiteOf", "isA", "partOf", "derivesFrom")

_SPEC_BY_NAME = {s.name: s for s in RELATION_SPECS}


# =========================================================================
# 本体驱动的 prompt 组装
# =========================================================================

def render_relation_definitions() -> str:
    """从 RELATION_SPECS 渲染抽取 prompt 的关系词表段(不改写)。"""
    parts = []
    for spec in RELATION_SPECS:
        domain = "、".join(_CLASS_ZH.get(c, c) for c in spec.domain)
        rng = "、".join(_CLASS_ZH.get(c, c) for c in spec.range)
        parts.append(
            f"### {spec.name} {spec.zh}\n"
            f"方向约束: {domain} → {rng}\n"
            f"{spec.description}"
        )
    return "\n\n".join(parts)


def render_atoms_table(atoms: list[dict]) -> str:
    """原子清单渲染为表格行(陈述截断控 prompt 体积)。"""
    lines = ["| 原子名 | 类型 | 一句话内容 |", "| --- | --- | --- |"]
    for a in atoms:
        name = str(a.get("name") or "").strip()
        cls = str(a.get("type") or "").strip()
        stmt = str(a.get("statement") or "").strip().replace("\n", " ")[:60]
        lines.append(f"| {name} | {_CLASS_ZH.get(cls, cls)} | {stmt} |")
    return "\n".join(lines)


RELATION_PROMPT = """You are an expert educational knowledge-graph builder. 在知识单元清单上抽取它们之间的关系。

## 关系词表(来自本体;每条含方向约束与判定描述)
{relation_definitions}

## 知识单元清单(共 {atom_count} 个)
{atoms_table}

## 输出 JSON schema
{{
  "relations": [
    {{
      "rel": "关系名(逐字匹配词表)",
      "source": "源原子名(逐字匹配清单)",
      "target": "目标原子名(逐字匹配清单)",
      "evidence": "依据:页码或一句话(来自文档的哪部分支持这条关系)"
    }}
  ]
}}

规则:
- source/target 只能从清单里选,名字逐字匹配;关系名逐字匹配词表。
- 方向遵守每条关系的 类型约束(如 prerequisiteOf 不允许事实作端点)。
- 只录直接关系:由已录关系传递可推出的不录(A→B、B→C 已录则不录 A→C)。
- 宁缺毋滥:证据不足或牵强的关系不录;每个原子平均 0.5-1.5 条出边是健康密度。
- 只输出一个 JSON 对象:无 markdown 围栏、无解释。evidence 与原子内容同语言。
"""


# =========================================================================
# 抽取与校验
# =========================================================================

async def extract_relations(atoms: list[dict], *, source_title: str) -> list[dict]:
    """对原子清单执行一次 LLM 关系抽取,返回候选关系列表。"""
    if not atoms:
        return []
    prompt = RELATION_PROMPT.format(
        relation_definitions=render_relation_definitions(),
        atom_count=len(atoms),
        atoms_table=render_atoms_table(atoms),
    )
    try:
        raw = await asyncio.wait_for(
            chat_complete(
                system_prompt="You are an expert educational knowledge-graph builder. Output ONLY valid JSON.",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.15,
                max_tokens=12_000,
            ),
            timeout=LLM_RELATION_TIMEOUT_SECONDS,
        )
    except (asyncio.TimeoutError, TimeoutError):
        return []
    except Exception:
        return []
    try:
        result = await load_llm_json(raw, expected="object")
    except Exception:
        return []
    if not isinstance(result, dict):
        return []
    return [r for r in (result.get("relations") or []) if isinstance(r, dict)]


def validate_relations(candidates: list[dict], atoms: list[dict]) -> tuple[list[dict], list[dict]]:
    """按 RELATION_SPECS 校验候选关系。

    校验:关系名在词表内;source/target 在原子清单内且类型满足
    domain/range;无自环;去重。返回 (通过, 被拒及原因)。
    """
    atom_types = {
        str(a.get("name") or "").strip(): str(a.get("type") or "").strip()
        for a in atoms
    }
    valid: list[dict] = []
    rejected: list[dict] = []
    seen: set[tuple] = set()

    for r in candidates:
        rel = str(r.get("rel") or "").strip()
        src = str(r.get("source") or "").strip()
        tgt = str(r.get("target") or "").strip()
        evidence = str(r.get("evidence") or "").strip()
        base = {"rel": rel, "source": src, "target": tgt}

        spec = _SPEC_BY_NAME.get(rel)
        if spec is None:
            rejected.append({**base, "reason": f"关系名不在词表: {rel}"})
            continue
        if src not in atom_types or tgt not in atom_types:
            rejected.append({**base, "reason": "原子不在清单内"})
            continue
        if src == tgt:
            rejected.append({**base, "reason": "自环"})
            continue
        if atom_types[src] not in spec.domain:
            rejected.append({**base, "reason": f"source 类型 {atom_types[src]} 不在域 {spec.domain}"})
            continue
        if atom_types[tgt] not in spec.range:
            rejected.append({**base, "reason": f"target 类型 {atom_types[tgt]} 不在值域 {spec.range}"})
            continue
        key = (rel, src, tgt)
        if key in seen:
            continue
        seen.add(key)
        valid.append({**base, "evidence": evidence, "cyclic": False})

    _flag_cycles(valid)
    return valid, rejected


def _flag_cycles(relations: list[dict]) -> None:
    """对传递关系标记参与环的边(可达性检测;标记保留,不丢弃)。

    边 (a→b) 成环 ⟺ 从 b 出发能回到 a,即 a ∈ reach[b]。
    (注意不能写成 b ∈ reach[a] —— b 从 a 直接可达恒真,全部边都会误标。)
    """
    for rel_name in _TRANSITIVE_RELATIONS:
        edges = [(r["source"], r["target"]) for r in relations if r["rel"] == rel_name]
        if not edges:
            continue
        reach: dict[str, set[str]] = {}
        adj: dict[str, list[str]] = {}
        for a, b in edges:
            adj.setdefault(a, []).append(b)
        for start in adj:
            stack, seen = [start], set()
            while stack:
                node = stack.pop()
                for nxt in adj.get(node, []):
                    if nxt not in seen:
                        seen.add(nxt)
                        stack.append(nxt)
            reach[start] = seen
        for r in relations:
            if r["rel"] != rel_name:
                continue
            # 直接赋值(而不是仅置 True):重跑时清掉旧标记
            r["cyclic"] = r["source"] in reach.get(r["target"], set())


# =========================================================================
# 持久化
# =========================================================================

def _relations_path(project_id: str) -> Path:
    return Path(settings.projects_dir) / project_id / "relations.json"


def save_relations(project_id: str, payload: dict) -> Path:
    path = _relations_path(project_id)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_relations(project_id: str) -> dict | None:
    path = _relations_path(project_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def graph_edges_for(project_id: str, title_to_id: dict) -> list[dict]:
    """把 relations.json 映射为图引擎边(名字→节点 id)。

    图引擎构图时调用:权威边(origin="ontology"),不过剪枝与打分。
    名字对不上的跳过(原子尚未成页或改名)。
    """
    data = load_relations(project_id)
    if not data:
        return []
    edges = []
    for r in data.get("relations", []):
        src = title_to_id.get(r.get("source"))
        tgt = title_to_id.get(r.get("target"))
        if not src or not tgt or src == tgt:
            continue
        edges.append({
            "source": src,
            "target": tgt,
            "edge_type": str(r.get("rel")),
            "weight": 1.0,
            "origin": "ontology",
            "evidence": str(r.get("evidence") or ""),
        })
    return edges


# =========================================================================
# 编排
# =========================================================================

def atoms_from_pages(project_id: str = "default") -> list[dict]:
    """从现有 wiki 页面重建原子清单(已导入项目的重跑入口)。"""
    from storage.wiki_store import list_wiki_pages

    atoms = []
    for meta in list_wiki_pages(project_id=project_id):
        cls = _PAGE_TYPE_TO_CLASS.get(str(meta.get("type") or ""))
        name = str(meta.get("title") or "").strip()
        if not cls or not name:
            continue
        atoms.append({
            "name": name,
            "type": cls,
            "statement": str(meta.get("summary") or ""),
        })
    return atoms


async def run_relation_extraction(
    atoms: list[dict],
    *,
    source_title: str,
    project_id: str = "default",
) -> dict:
    """Stage 1b 入口:原子清单 → 抽取 → 校验 → relations.json。"""
    candidates = await extract_relations(atoms, source_title=source_title)
    valid, rejected = validate_relations(candidates, atoms)
    payload = {
        "version": 1,
        "source_title": source_title,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "atom_count": len(atoms),
        "atoms": [{"name": a["name"], "type": a["type"]} for a in atoms],
        "relations": valid,
        "rejected": rejected,
    }
    save_relations(project_id, payload)
    cyclic = sum(1 for r in valid if r.get("cyclic"))
    print(f"[relations] {project_id}: 候选 {len(candidates)},通过 {len(valid)}"
          f"(环标记 {cyclic}),拒绝 {len(rejected)} → relations.json")
    return payload
