"""Materials-science domain graph extraction.

This module is intentionally independent from the generic educational wiki
pipeline.  It turns a *single course-material excerpt* into a domain graph
whose nodes and edges follow the materials-science ontology used by the
research prototype:

    composition -> processing -> structure -> property -> performance
                                        -> failure -> diagnosis -> design

The service is deliberately small and prompt-driven so it can be evaluated
in isolation before being wired into the full ingest pipeline.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from typing import Any

from services.llm_client import chat_complete


# ---------------------------------------------------------------------------
# Ontology
# ---------------------------------------------------------------------------

MATERIALS_NODE_TYPES = {
    "concept",
    "formula",
    "mechanism",
    "property",
    "material",
    "composition",
    "structure",
    "processing",
    "instrument",
    "algorithm",
    "descriptor",
    "dataset",
    "failure_mode",
    "case",
    "safety_rule",
}

MATERIALS_EDGE_TYPES = {
    "has_composition",
    "composition_to_structure",
    "processed_by",
    "results_in_structure",
    "determines_property",
    "explained_by",
    "measured_by",
    "characterized_by",
    "modeled_by",
    "predicted_by",
    "uses_descriptor",
    "leads_to_failure",
    "diagnosed_by",
    "prevented_by",
    "safety_constraint_of",
    "supports_course",
    "prerequisite",
    "related",
}

_NODE_TYPE_ALIASES = {
    "course": "concept",
    "knowledge": "concept",
    "term": "concept",
    "definition": "concept",
    "principle": "mechanism",
    "theory": "mechanism",
    "process": "processing",
    "experiment": "case",
    "example": "case",
    "method": "algorithm",
    "model": "algorithm",
    "software": "algorithm",
    "data": "dataset",
    "database": "dataset",
    "device": "instrument",
    "equipment": "instrument",
    "failure": "failure_mode",
    "failure mode": "failure_mode",
    "safety": "safety_rule",
    "rule": "safety_rule",
    "material system": "material",
    "chemical composition": "composition",
    "microstructure": "structure",
    "phase": "structure",
    "property": "property",
    "performance": "property",
}

_EDGE_TYPE_ALIASES = {
    "composition_to_structure": "composition_to_structure",
    "has_chemical_composition": "has_composition",
    "processing_to_structure": "results_in_structure",
    "structure_to_property": "determines_property",
    "mechanism_to_property": "determines_property",
    "property_to_failure": "leads_to_failure",
    "instrument_to_observable": "measured_by",
    "method_to_measurement": "measured_by",
    "algorithm_to_prediction": "predicted_by",
    "model_to_property": "modeled_by",
    "descriptor_to_model": "uses_descriptor",
    "failure_to_diagnosis": "diagnosed_by",
    "course_support": "supports_course",
    "prerequisite_of": "prerequisite",
    "related_to": "related",
    "see_also": "related",
}


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

COURSE_PROFILE_PROMPT = """You are an expert materials-science curriculum analyst.
Analyze the following course excerpt and return a concise course profile.

## Source title
{source_title}

## Course excerpt
{content}

## Output JSON schema
{{
  "course": "course name, or the most likely course if not explicit",
  "topic": "main topic in this excerpt",
  "chapters": [
    {{"title": "chapter or lecture title", "summary": "one-sentence summary"}}
  ],
  "prerequisite_courses": ["likely prerequisite courses"],
  "core_competencies": ["materials-science competencies exercised by this excerpt"]
}}

Rules:
- Use only information supported by the excerpt.
- Keep every string concise.
- Return ONLY one valid JSON object, with no markdown fences or commentary.
"""


KNOWLEDGE_ATOM_PROMPT = """You are an expert materials-science knowledge engineer.
Extract the most important knowledge atoms from the excerpt below.

## Source title
{source_title}

## Course profile
{profile}

## Course excerpt
{content}

## Allowed node types
concept, formula, mechanism, property, material, composition, structure,
processing, instrument, algorithm, descriptor, dataset, failure_mode, case,
safety_rule

## Output JSON schema
{{
  "nodes": [
    {{
      "label": "human-readable atom name",
      "type": "one allowed node type",
      "definition": "one-sentence definition or role",
      "source_ref": "page, section, or other evidence locator; omit if unknown"
    }}
  ]
}}

Rules:
- Extract 5 to 20 atoms when the excerpt supports them.
- Prefer domain-specific atoms over generic study words.
- Include at least one mechanism or property when the excerpt supports it.
- Do not invent facts not supported by the excerpt.
- Return ONLY one valid JSON object.
"""


RELATION_PROMPT = """You are an expert materials-science knowledge-graph constructor.
Infer typed relations between the provided knowledge atoms.

## Source title
{source_title}

## Knowledge atoms
{nodes}

## Course excerpt
{content}

## Allowed edge types and direction
Use the exact source -> target direction below:

- has_composition: material -> composition
- composition_to_structure: composition -> structure
- processed_by: material -> processing
- results_in_structure: processing -> structure
- determines_property: structure or mechanism -> property
- explained_by: property -> mechanism
- measured_by: property -> instrument or method
- characterized_by: structure -> instrument or method
- modeled_by: property or phenomenon -> model or algorithm
- predicted_by: target property -> algorithm or model
- uses_descriptor: model or algorithm -> descriptor
- leads_to_failure: service condition or property -> failure_mode
- diagnosed_by: failure_mode -> diagnostic method
- prevented_by: failure_mode -> prevention method
- safety_constraint_of: safety_rule -> operation or experiment
- supports_course: knowledge atom -> course
- prerequisite: prerequisite atom -> dependent atom
- related: any two related atoms

Examples:
- 晶粒细化 -> 屈服强度: determines_property
- 屈服强度 -> 位错运动: explained_by
- 热导率 -> 激光闪射法: measured_by
- 马氏体 -> XRD: characterized_by
- 热导率 -> 第一性原理计算: modeled_by

## Output JSON schema
{{
  "edges": [
    {{
      "source": "node label or id",
      "target": "node label or id",
      "type": "one allowed edge type",
      "evidence": "short evidence phrase from the excerpt",
      "confidence": 0.0
    }}
  ]
}}

Rules:
- Only connect atoms that appear in the provided node list.
- Use the most specific edge type available.
- Confidence must be between 0 and 1.
- Prefer 4 to 15 high-quality edges over many weak edges.
- Return ONLY one valid JSON object.
"""


PEDAGOGY_PROMPT = """You are an expert materials-science educator.
Infer pedagogical attributes for each knowledge atom.

## Course profile
{profile}

## Knowledge atoms
{nodes}

## Course excerpt
{content}

## Output JSON schema
{{
  "nodes": [
    {{
      "label": "atom label",
      "difficulty": 3,
      "bloom_level": "remember|understand|apply|analyze|evaluate|create",
      "prerequisites": ["other atom labels"],
      "common_misconceptions": ["one-sentence misconception"],
      "learning_objectives": ["one-sentence objective"],
      "estimated_minutes": 10,
      "related_courses": ["likely course names"]
    }}
  ]
}}

Rules:
- Return one entry for every knowledge atom when possible.
- Difficulty is an integer from 1 to 5.
- Do not invent misconceptions; use an empty array when unsure.
- Return ONLY one valid JSON object.
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _normalize_node_type(value: Any) -> str:
    text = _clean_text(value).lower().replace("-", "_").replace(" ", "_")
    text = _NODE_TYPE_ALIASES.get(text, text)
    return text if text in MATERIALS_NODE_TYPES else "concept"


def _normalize_edge_type(value: Any) -> str:
    text = _clean_text(value).lower().replace("-", "_").replace(" ", "_")
    text = _EDGE_TYPE_ALIASES.get(text, text)
    return text if text in MATERIALS_EDGE_TYPES else "related"


def _node_id(label: str, node_type: str) -> str:
    raw = f"{node_type}:{_clean_text(label).lower()}"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]
    return f"mat_{digest}"


def _clamp(value: Any, low: float, high: float, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(low, min(high, number))


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if not text:
        return text
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 3:
            text = parts[1].strip()
            if text.lower().startswith("json"):
                text = text[4:].strip()
    return text


def _loads_llm_json(text: str) -> Any:
    """Parse a JSON object or array from an LLM response."""
    cleaned = _strip_code_fence(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Some models prefix the JSON with a short sentence. Find the first
    # structural token and the last matching closing brace/bracket.
    starts = [i for i in (cleaned.find("{"), cleaned.find("[")) if i >= 0]
    if not starts:
        raise ValueError("LLM response did not contain JSON")
    start = min(starts)
    opener = cleaned[start]
    closer = "}" if opener == "{" else "]"
    end = cleaned.rfind(closer)
    if end <= start:
        raise ValueError("LLM response contained incomplete JSON")
    candidate = cleaned[start : end + 1]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as exc:
        # Remove trailing commas before a closing delimiter, a common LLM
        # formatting error that is otherwise valid JSON in intent.
        repaired = re.sub(r",\s*([}\]])", r"\1", candidate)
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            raise ValueError(f"Invalid LLM JSON: {exc}") from exc


async def _ask_json(prompt: str, *, max_tokens: int = 4096) -> Any:
    system_prompt = (
        "You are a precise materials-science knowledge engineer. "
        "Output only valid JSON."
    )
    response = await chat_complete(
        system_prompt=system_prompt,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        max_tokens=max_tokens,
    )

    try:
        return _loads_llm_json(response)
    except ValueError:
        # Domain models occasionally wrap JSON in prose or return an empty
        # completion. A single deterministic repair pass keeps the public
        # pipeline robust without silently accepting malformed data.
        repair_prompt = (
            "The previous model output was not valid JSON. "
            "Return only the corrected JSON object or array that answers the "
            "original request. Do not add markdown fences or commentary.\n\n"
            "Original request:\n"
            f"{prompt[:12000]}\n\n"
            "Previous output:\n"
            f"{response[:12000]}"
        )
        repaired = await chat_complete(
            system_prompt=system_prompt,
            messages=[{"role": "user", "content": repair_prompt}],
            temperature=0.0,
            max_tokens=max_tokens,
        )
        return _loads_llm_json(repaired)


def _format_profile(profile: dict[str, Any]) -> str:
    return json.dumps(profile, ensure_ascii=False, indent=2)


def _format_nodes(nodes: Iterable[dict[str, Any]]) -> str:
    compact = [
        {
            "id": node.get("id"),
            "label": node.get("label"),
            "type": node.get("node_type"),
            "definition": node.get("definition", ""),
        }
        for node in nodes
    ]
    return json.dumps(compact, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Extraction stages
# ---------------------------------------------------------------------------


async def extract_course_profile(content: str, *, source_title: str) -> dict[str, Any]:
    prompt = COURSE_PROFILE_PROMPT.format(
        source_title=source_title,
        content=content,
    )
    data = await _ask_json(prompt, max_tokens=3000)
    if not isinstance(data, dict):
        raise ValueError("Course profile response must be a JSON object")
    return {
        "course": _clean_text(data.get("course")) or source_title,
        "topic": _clean_text(data.get("topic")),
        "chapters": [
            {
                "title": _clean_text(item.get("title")),
                "summary": _clean_text(item.get("summary")),
            }
            for item in data.get("chapters", [])
            if isinstance(item, dict)
        ],
        "prerequisite_courses": [
            _clean_text(item) for item in data.get("prerequisite_courses", []) if _clean_text(item)
        ],
        "core_competencies": [
            _clean_text(item) for item in data.get("core_competencies", []) if _clean_text(item)
        ],
    }


async def extract_knowledge_atoms(
    content: str,
    *,
    source_title: str,
    profile: dict[str, Any],
) -> list[dict[str, Any]]:
    prompt = KNOWLEDGE_ATOM_PROMPT.format(
        source_title=source_title,
        profile=_format_profile(profile),
        content=content,
    )
    data = await _ask_json(prompt, max_tokens=8000)
    if not isinstance(data, dict) or not isinstance(data.get("nodes"), list):
        raise ValueError("Knowledge-atom response must contain a nodes array")

    nodes: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in data["nodes"]:
        if not isinstance(item, dict):
            continue
        label = _clean_text(item.get("label"))
        if not label:
            continue
        node_type = _normalize_node_type(item.get("type"))
        node_id = _node_id(label, node_type)
        if node_id in seen:
            continue
        seen.add(node_id)
        nodes.append(
            {
                "id": node_id,
                "label": label,
                "node_type": node_type,
                "definition": _clean_text(item.get("definition")),
                "source_ref": _clean_text(item.get("source_ref")) or None,
            }
        )
    return nodes


async def extract_relations(
    content: str,
    *,
    source_title: str,
    nodes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not nodes:
        return []
    prompt = RELATION_PROMPT.format(
        source_title=source_title,
        nodes=_format_nodes(nodes),
        content=content,
    )
    data = await _ask_json(prompt, max_tokens=8000)
    if not isinstance(data, dict) or not isinstance(data.get("edges"), list):
        raise ValueError("Relation response must contain an edges array")

    aliases: dict[str, str] = {}
    for node in nodes:
        aliases[str(node["id"]).lower()] = node["id"]
        aliases[str(node["label"]).lower()] = node["id"]
        aliases[_clean_text(node["label"]).lower()] = node["id"]

    valid_ids = {node["id"] for node in nodes}
    edges: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in data["edges"]:
        if not isinstance(item, dict):
            continue
        source = aliases.get(_clean_text(item.get("source")).lower())
        target = aliases.get(_clean_text(item.get("target")).lower())
        if not source or not target or source not in valid_ids or target not in valid_ids:
            continue
        edge_type = _normalize_edge_type(item.get("type"))
        key = (source, target, edge_type)
        if key in seen:
            continue
        seen.add(key)
        confidence = _clamp(item.get("confidence"), 0.0, 1.0, 0.7)
        edges.append(
            {
                "source": source,
                "target": target,
                "edge_type": edge_type,
                "evidence": _clean_text(item.get("evidence")),
                "confidence": confidence,
                "weight": round(0.2 + confidence * 0.8, 3),
            }
        )
    return edges


async def extract_pedagogy(
    content: str,
    *,
    profile: dict[str, Any],
    nodes: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    if not nodes:
        return {}
    prompt = PEDAGOGY_PROMPT.format(
        profile=_format_profile(profile),
        nodes=_format_nodes(nodes),
        content=content,
    )
    data = await _ask_json(prompt, max_tokens=8000)
    if not isinstance(data, dict) or not isinstance(data.get("nodes"), list):
        raise ValueError("Pedagogy response must contain a nodes array")

    by_label: dict[str, dict[str, Any]] = {}
    for item in data["nodes"]:
        if not isinstance(item, dict):
            continue
        label = _clean_text(item.get("label")).lower()
        if label:
            by_label[label] = item

    result: dict[str, dict[str, Any]] = {}
    for node in nodes:
        item = by_label.get(str(node["label"]).lower(), {})
        difficulty_raw = item.get("difficulty")
        difficulty = int(difficulty_raw) if isinstance(difficulty_raw, (int, float)) else None
        if difficulty is not None:
            difficulty = max(1, min(5, int(difficulty)))
        result[node["id"]] = {
            "difficulty": difficulty,
            "bloom_level": _clean_text(item.get("bloom_level")).lower() or None,
            "prerequisites": [
                _clean_text(value) for value in item.get("prerequisites", []) if _clean_text(value)
            ],
            "common_misconceptions": [
                _clean_text(value)
                for value in item.get("common_misconceptions", [])
                if _clean_text(value)
            ],
            "learning_objectives": [
                _clean_text(value)
                for value in item.get("learning_objectives", [])
                if _clean_text(value)
            ],
            "estimated_minutes": (
                max(1.0, float(item.get("estimated_minutes")))
                if isinstance(item.get("estimated_minutes"), (int, float))
                else None
            ),
            "related_courses": [
                _clean_text(value) for value in item.get("related_courses", []) if _clean_text(value)
            ],
        }
    return result


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


async def extract_materials_graph(
    content: str,
    *,
    source_title: str,
) -> dict[str, Any]:
    """Run the four-stage materials-graph extraction pipeline.

    The stages are intentionally separated so each can be independently
    evaluated, replaced, or benchmarked in the paper:
    1. course profile
    2. knowledge atoms
    3. typed relations
    4. pedagogical attributes
    """
    if not _clean_text(content):
        raise ValueError("content must not be empty")

    profile = await extract_course_profile(content, source_title=source_title)
    nodes = await extract_knowledge_atoms(content, source_title=source_title, profile=profile)
    edges = await extract_relations(content, source_title=source_title, nodes=nodes)
    pedagogy = await extract_pedagogy(content, profile=profile, nodes=nodes)

    enriched_nodes: list[dict[str, Any]] = []
    for node in nodes:
        extra = pedagogy.get(node["id"], {})
        enriched_nodes.append({**node, **extra})

    return {
        "source_title": source_title,
        "course_profile": profile,
        "nodes": enriched_nodes,
        "edges": edges,
        "stats": {
            "node_count": len(enriched_nodes),
            "edge_count": len(edges),
            "node_types": sorted({node["node_type"] for node in enriched_nodes}),
            "edge_types": sorted({edge["edge_type"] for edge in edges}),
        },
    }
