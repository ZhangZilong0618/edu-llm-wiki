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

_RELATION_DIRECTION_RULES: dict[str, tuple[set[str], set[str]]] = {
    "has_composition": ({"material"}, {"composition"}),
    "composition_to_structure": ({"composition"}, {"structure"}),
    "processed_by": ({"material"}, {"processing"}),
    "results_in_structure": ({"processing"}, {"structure"}),
    "determines_property": ({"structure", "mechanism"}, {"property"}),
    "explained_by": ({"property", "failure_mode"}, {"mechanism"}),
    "measured_by": ({"property"}, {"instrument", "algorithm"}),
    "characterized_by": (
        {"structure", "failure_mode"},
        {"instrument", "algorithm", "property"},
    ),
    "modeled_by": ({"property", "concept"}, {"algorithm"}),
    "predicted_by": ({"property"}, {"algorithm"}),
    "uses_descriptor": ({"algorithm"}, {"descriptor"}),
    "leads_to_failure": (
        {"property", "mechanism", "concept", "processing", "material"},
        {"failure_mode"},
    ),
    "diagnosed_by": ({"failure_mode"}, {"instrument", "algorithm"}),
    "prevented_by": (
        {"failure_mode"},
        {"processing", "material", "concept", "safety_rule"},
    ),
    "safety_constraint_of": ({"safety_rule"}, {"processing", "case"}),
}

# Type-compatible relation hypotheses. These are not facts; the LLM must
# confirm each one against the source excerpt. They constrain free-form
# generation to the materials-science ontology and make candidate generation
# deterministic and testable.
_RELATION_TEMPLATES: dict[tuple[str, str], tuple[tuple[str, float], ...]] = {
    ("material", "composition"): (("has_composition", 0.90),),
    ("composition", "structure"): (("composition_to_structure", 0.90),),
    ("material", "processing"): (("processed_by", 0.88),),
    ("processing", "structure"): (("results_in_structure", 0.90),),
    ("structure", "property"): (("determines_property", 0.92),),
    ("mechanism", "property"): (("determines_property", 0.90),),
    ("property", "mechanism"): (("explained_by", 0.88),),
    ("property", "instrument"): (("measured_by", 0.90),),
    ("property", "algorithm"): (
        ("modeled_by", 0.84),
        ("predicted_by", 0.84),
    ),
    ("structure", "instrument"): (("characterized_by", 0.88),),
    ("algorithm", "descriptor"): (("uses_descriptor", 0.82),),
    ("property", "failure_mode"): (("leads_to_failure", 0.88),),
    ("mechanism", "failure_mode"): (("leads_to_failure", 0.88),),
    ("concept", "failure_mode"): (("leads_to_failure", 0.76),),
    ("processing", "failure_mode"): (("leads_to_failure", 0.74),),
    ("material", "failure_mode"): (("leads_to_failure", 0.74),),
    ("failure_mode", "mechanism"): (("explained_by", 0.88),),
    ("failure_mode", "property"): (("characterized_by", 0.84),),
    ("failure_mode", "instrument"): (("diagnosed_by", 0.86),),
    ("failure_mode", "safety_rule"): (("prevented_by", 0.80),),
    ("failure_mode", "algorithm"): (("diagnosed_by", 0.82),),
    ("failure_mode", "processing"): (("prevented_by", 0.84),),
    ("failure_mode", "material"): (("prevented_by", 0.80),),
    ("safety_rule", "processing"): (("safety_constraint_of", 0.86),),
    ("safety_rule", "case"): (("safety_constraint_of", 0.82),),
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

## Node-type definitions
- material: a named alloy, metal, ceramic, polymer, or material system
- composition: chemical constituents or composition range
- processing: a synthesis, heat-treatment, machining, or service operation
- structure: a phase, microstructure, defect, or morphological feature
- property: a measurable or observable characteristic
- mechanism: a causal process that explains a property or failure
- failure_mode: a named damage or failure mode (e.g. SCC, corrosion fatigue, hydrogen embrittlement)
- instrument: a characterization or measurement device/method
- algorithm: a model, simulation, prediction, or data method
- descriptor: an input feature used by a model
- dataset: experimental or simulation data
- case: a concrete example, accident, or experiment
- safety_rule: a protection, operating, or safety constraint
- concept: use only when no more specific type fits

## Output JSON schema
{{
  "nodes": [
    {{
      "label": "human-readable atom name",
      "type": "one allowed node type",
      "definition": "one-sentence definition or role",
      "source_term": "exact contiguous term or short phrase from the excerpt",
      "source_ref": "page, section, or other evidence locator; omit if unknown"
    }}
  ]
}}

Rules:
- Extract 5 to 20 atoms when the excerpt supports them.
- Prefer domain-specific atoms over generic study words.
- Write each label in the excerpt's primary language and use the exact source term when available.
- Fill source_term with a verbatim contiguous phrase copied from the excerpt; never invent or merely repeat a normalized label.
- If the label is abstract, source_term should quote the supporting phrase (e.g. label “SCC发生三条件” → source_term “三个条件同时满足”).
- Include material, processing, structure, property, mechanism, failure mode, and instrument atoms when the excerpt supports them.
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

## Relation candidates
{candidates}

## Course excerpt
{content}

## Allowed edge types and direction
Use the exact source -> target direction below:

- has_composition: material -> composition
- composition_to_structure: composition -> structure
- processed_by: material -> processing
- results_in_structure: processing -> structure
- determines_property: structure or mechanism -> property
- explained_by: property or failure_mode -> mechanism
- measured_by: property -> instrument or method
- characterized_by: structure or failure_mode -> instrument, method, or observable property
- modeled_by: property or phenomenon -> model or algorithm
- predicted_by: target property -> algorithm or model
- uses_descriptor: model or algorithm -> descriptor
- leads_to_failure: service condition, property, or mechanism -> failure_mode
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
- Relation candidates are hypotheses from node-type ontology and text co-occurrence, not facts.
- Evaluate the candidates and accept only those supported by the excerpt.
- You may reject candidates, merge duplicate directions, or add missing relations with explicit evidence.
- Prefer connecting every atom when the excerpt supports it, but never force an unsupported relation.
- Use the most specific edge type available.
- Never use related when the evidence supports one of the typed relations above.
- For mechanisms that cause failures, prefer leads_to_failure or explained_by instead of related.
- For observable fracture or damage features, prefer characterized_by instead of related.
- Confidence must be between 0 and 1.
- Prefer 4 to 20 high-quality edges over many weak edges.
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


def _relation_direction_is_valid(
    source: dict[str, Any],
    target: dict[str, Any],
    edge_type: str,
) -> bool:
    rule = _RELATION_DIRECTION_RULES.get(edge_type)
    if rule is None:
        return True
    source_types, target_types = rule
    return source["node_type"] in source_types and target["node_type"] in target_types


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


def _mask_non_evidence_sections(content: str) -> str:
    """Blank headings and link-list sections while preserving character offsets."""
    ignored_headings = {"关联知识", "相关知识", "进一步问题"}
    masked_lines: list[str] = []
    current_heading = ""
    for line in content.splitlines(keepends=True):
        stripped = line.strip()
        heading_match = re.match(r"^#{1,6}\s+(.+?)\s*$", stripped)
        if heading_match:
            current_heading = heading_match.group(1)
            masked_lines.append(" " * len(line))
            continue
        if current_heading in ignored_headings:
            masked_lines.append(" " * len(line))
        else:
            masked_lines.append(line)
    return "".join(masked_lines)


def _label_variants(label: str) -> list[str]:
    """Return literal label variants used to locate an atom in source text."""
    cleaned = _clean_text(label).lower()
    variants = [cleaned]
    without_parentheses = re.sub(r"\s*[（(][^）)]*[）)]\s*", " ", cleaned).strip()
    if without_parentheses and without_parentheses != cleaned:
        variants.append(without_parentheses)
    for separator in ("、", "/", "／"):
        if separator in cleaned:
            variants.extend(part.strip() for part in cleaned.split(separator) if len(part.strip()) > 1)
    return list(dict.fromkeys(variants))


def _node_search_terms(node: dict[str, Any]) -> list[str]:
    terms: list[str] = []
    for value in (node.get("label"), node.get("source_term")):
        terms.extend(_label_variants(str(value or "")))
    return list(dict.fromkeys(terms))


def _label_spans(label: str, text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for variant in _label_variants(label):
        if not variant:
            continue
        spans.extend(
            (match.start(), match.end())
            for match in re.finditer(re.escape(variant), text)
        )
    return spans


def _non_nested_spans(
    node: dict[str, Any],
    nodes: list[dict[str, Any]],
    text: str,
) -> list[tuple[int, int]]:
    """Find atom mentions without counting text nested inside a longer atom."""
    spans = [
        (match.start(), match.end())
        for variant in _node_search_terms(node)
        for match in re.finditer(re.escape(variant), text)
    ]
    spans = sorted(set(spans))
    if not spans:
        return []
    own_length = max(
        (len(variant) for variant in _node_search_terms(node)),
        default=0,
    )
    blocking_spans: list[tuple[int, int, int]] = []
    for other in nodes:
        if other["id"] == node["id"]:
            continue
        other_length = max(
            (len(variant) for variant in _label_variants(str(other.get("label") or ""))),
            default=0,
        )
        if other_length <= own_length:
            continue
        blocking_spans.extend(
            (start, end, other_length)
            for variant in _node_search_terms(other)
            for match in re.finditer(re.escape(variant), text)
            for start, end in ((match.start(), match.end()),)
        )
    return [
        span for span in spans
        if not any(
            span[0] >= start and span[1] <= end
            for start, end, _length in blocking_spans
        )
    ]


def _text_chunks(content: str) -> list[tuple[str, str]]:
    """Split text into sentence-sized evidence chunks without losing text."""
    chunks: list[tuple[str, str]] = []
    for match in re.finditer(r"[^\n。！？；;!?]+[。！？；;!?]?", content):
        text = match.group(0).strip()
        if text:
            chunks.append((text, text.lower()))
    return chunks


def _snippet_at(content: str, start: int, end: int, radius: int = 120) -> str:
    centre = (start + end) // 2
    left = max(0, centre - radius)
    right = min(len(content), centre + radius)
    snippet = re.sub(r"\s+", " ", content[left:right]).strip()
    if left > 0:
        snippet = "..." + snippet
    if right < len(content):
        snippet += "..."
    return snippet[:360]


def _relation_hypotheses(
    source: dict[str, Any],
    target: dict[str, Any],
) -> list[tuple[dict[str, Any], dict[str, Any], str, float]]:
    """Return directed hypotheses without reversing an edge's semantics."""
    direct = _RELATION_TEMPLATES.get((source["node_type"], target["node_type"]), ())
    reverse = _RELATION_TEMPLATES.get((target["node_type"], source["node_type"]), ())
    hypotheses = [
        (source, target, edge_type, specificity)
        for edge_type, specificity in direct
    ]
    hypotheses.extend(
        (target, source, edge_type, specificity * 0.92)
        for edge_type, specificity in reverse
    )
    return hypotheses


def build_relation_candidates(
    content: str,
    nodes: list[dict[str, Any]],
    *,
    max_candidates: int = 48,
) -> list[dict[str, Any]]:
    """Build explainable relation hypotheses for the LLM to verify.

    Candidate generation combines three signals:
    1. the materials-science type ontology (composition → processing →
       structure → property → failure);
    2. sentence-level co-occurrence, which supplies concrete evidence;
    3. document proximity, which supplies weaker but still source-backed
       candidates when an article mentions two atoms in adjacent clauses.

    The result is deliberately a *candidate list*, not a final edge list: the
    model must confirm or reject each hypothesis from the excerpt.
    """
    if not nodes:
        return []

    matching_content = _mask_non_evidence_sections(content)
    lower_content = matching_content.lower()
    positions: dict[str, list[int]] = {
        node["id"]: [span[0] for span in _non_nested_spans(node, nodes, lower_content)]
        for node in nodes
    }

    chunks = _text_chunks(matching_content)
    candidates: dict[tuple[str, str, str], dict[str, Any]] = {}

    def add_candidate(
        source: dict[str, Any],
        target: dict[str, Any],
        edge_type: str,
        specificity: float,
        evidence: str,
        same_sentence: bool,
        distance: int | None,
        reason: str,
    ) -> None:
        if source["id"] == target["id"]:
            return
        key = (source["id"], target["id"], edge_type)
        proximity = 0.0
        if distance is not None:
            proximity = max(0.0, 1.0 - distance / 1000.0) * 0.22
        score = min(
            0.95,
            specificity * 0.55
            + (0.24 if same_sentence else 0.08)
            + proximity,
        )
        candidate = {
            "source": source["id"],
            "target": target["id"],
            "edge_type": edge_type,
            "evidence": evidence[:360],
            "score": round(score, 3),
            "reason": reason,
        }
        existing = candidates.get(key)
        if existing is None or candidate["score"] > existing["score"]:
            candidates[key] = candidate

    # Sentence-level candidates are the strongest textual evidence.
    for chunk, lower_chunk in chunks:
        spans_by_node = {
            node["id"]: _non_nested_spans(node, nodes, lower_chunk)
            for node in nodes
        }
        present = [node for node in nodes if spans_by_node[node["id"]]]
        for i, source in enumerate(present):
            for target in present[i + 1:]:
                source_spans = spans_by_node[source["id"]]
                target_spans = spans_by_node[target["id"]]
                distance = min(
                    abs(source_start - target_start)
                    for source_start, _source_end in source_spans
                    for target_start, _target_end in target_spans
                )
                hypotheses = _relation_hypotheses(source, target)
                if hypotheses:
                    for hypothesis_source, hypothesis_target, edge_type, specificity in hypotheses:
                        add_candidate(
                            hypothesis_source, hypothesis_target, edge_type, specificity,
                            chunk, True, distance,
                            "same-sentence co-occurrence + type-compatible relation",
                        )
                else:
                    add_candidate(
                        source, target, "related", 0.52,
                        chunk, True, distance,
                        "same-sentence co-occurrence",
                    )

    # Proximity candidates keep atoms connected when the article discusses
    # them in nearby paragraphs rather than the same sentence.
    for i, source in enumerate(nodes):
        source_positions = positions[source["id"]]
        if not source_positions:
            continue
        for target in nodes[i + 1:]:
            target_positions = positions[target["id"]]
            if not target_positions:
                continue
            start, end = min(
                ((a, b) for a in source_positions for b in target_positions),
                key=lambda pair: abs(pair[0] - pair[1]),
            )
            distance = abs(start - end)
            if distance > 700:
                continue
            hypotheses = _relation_hypotheses(source, target)
            evidence = _snippet_at(matching_content, min(start, end), max(start, end))
            if hypotheses:
                for hypothesis_source, hypothesis_target, edge_type, specificity in hypotheses:
                    add_candidate(
                        hypothesis_source, hypothesis_target, edge_type, specificity,
                        evidence, False, distance,
                        "nearby document mentions + type-compatible relation",
                    )
            else:
                add_candidate(
                    source, target, "related", 0.42,
                    evidence, False, distance,
                    "nearby document mentions",
                )

    # Ensure every extracted atom is represented in the candidate set. If it
    # never appears literally, fall back to an ontology-compatible peer so the
    # model still receives a concrete hypothesis to confirm or reject.
    covered = {
        candidate["source"] for candidate in candidates.values()
    } | {
        candidate["target"] for candidate in candidates.values()
    }
    for node in nodes:
        if node["id"] in covered:
            continue
        peers = [
            other for other in nodes
            if other["id"] != node["id"] and _relation_hypotheses(node, other)
        ]
        if peers:
            source, target, edge_type, specificity = _relation_hypotheses(node, peers[0])[0]
            add_candidate(
                source, target, edge_type, specificity,
                "", False, None,
                "type-compatible fallback; verify against the full excerpt",
            )
            continue
        other = next((item for item in nodes if item["id"] != node["id"]), None)
        if other is None:
            continue
        add_candidate(
            node, other, "related", 0.35,
            "", False, None,
            "type-agnostic fallback; verify against the full excerpt",
        )

    # Preserve candidate coverage first, then rank the rest by score. This
    # avoids a high-scoring cluster crowding out atoms from other sections.
    by_id = {node["id"]: node for node in nodes}
    selected: list[dict[str, Any]] = []
    selected_keys: set[tuple[str, str, str]] = set()
    represented: set[str] = set()

    def consider(candidate: dict[str, Any]) -> None:
        key = (candidate["source"], candidate["target"], candidate["edge_type"])
        if key in selected_keys:
            return
        selected.append(candidate)
        selected_keys.add(key)
        represented.add(candidate["source"])
        represented.add(candidate["target"])

    for candidate in sorted(candidates.values(), key=lambda item: -item["score"]):
        if len(selected) >= max_candidates:
            break
        if candidate["source"] not in represented or candidate["target"] not in represented:
            consider(candidate)
    for candidate in sorted(candidates.values(), key=lambda item: -item["score"]):
        if len(selected) >= max_candidates:
            break
        consider(candidate)

    selected.sort(
        key=lambda item: (
            -item["score"],
            by_id[item["source"]]["label"],
            by_id[item["target"]]["label"],
            item["edge_type"],
        )
    )
    return selected


def _format_relation_candidates(
    candidates: list[dict[str, Any]],
    nodes: list[dict[str, Any]],
) -> str:
    if not candidates:
        return "(none)"
    by_id = {node["id"]: node for node in nodes}
    lines = []
    for item in candidates:
        source_label = by_id[item["source"]]["label"]
        target_label = by_id[item["target"]]["label"]
        lines.append(
            f"- {source_label} [{item['source']}] -> {target_label} [{item['target']}] | "
            f"{item['edge_type']} | score={item['score']:.2f} | "
            f"evidence={item['evidence'] or '(none)'}"
        )
    return "\n".join(lines)


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
            "source_term": node.get("source_term", ""),
        }
        for node in nodes
    ]
    return json.dumps(compact, ensure_ascii=False, indent=2)


def _graph_components(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> list[set[str]]:
    adjacency: dict[str, set[str]] = {node["id"]: set() for node in nodes}
    for edge in edges:
        if edge["source"] in adjacency and edge["target"] in adjacency:
            adjacency[edge["source"]].add(edge["target"])
            adjacency[edge["target"]].add(edge["source"])

    remaining = set(adjacency)
    components: list[set[str]] = []
    while remaining:
        root = next(iter(remaining))
        stack = [root]
        component = {root}
        while stack:
            current = stack.pop()
            for neighbor in adjacency[current]:
                if neighbor not in component:
                    component.add(neighbor)
                    stack.append(neighbor)
        components.append(component)
        remaining -= component
    return components


def _bridge_disconnected_components(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    relation_candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Connect components using conservative, low-confidence related edges.

    The relation model may reject a candidate because the excerpt does not
    support a typed causal relation. That should not leave an atom visually
    isolated when the candidate generator found a source-backed or
    ontology-compatible connection. Bridges are always marked ``related`` and
    capped at low confidence so they cannot masquerade as verified mechanisms.
    """
    valid_ids = {node["id"] for node in nodes}
    components = _graph_components(nodes, edges)
    if len(components) <= 1:
        return edges

    component_by_node = {
        node_id: index
        for index, component in enumerate(components)
        for node_id in component
    }
    existing = {
        (edge["source"], edge["target"], edge["edge_type"]) for edge in edges
    }
    bridged = list(edges)
    used_candidates: set[tuple[str, str]] = set()

    while len(_graph_components(nodes, bridged)) > 1:
        current_components = _graph_components(nodes, bridged)
        component_by_node = {
            node_id: index
            for index, component in enumerate(current_components)
            for node_id in component
        }
        choices = [
            candidate for candidate in relation_candidates
            if candidate["source"] in valid_ids
            and candidate["target"] in valid_ids
            and component_by_node[candidate["source"]] != component_by_node[candidate["target"]]
            and (candidate["source"], candidate["target"]) not in used_candidates
            and (candidate["target"], candidate["source"]) not in used_candidates
        ]
        if not choices:
            break
        candidate = max(
            choices,
            key=lambda item: (
                bool(item.get("evidence")),
                item.get("score", 0.0),
            ),
        )
        pair = (candidate["source"], candidate["target"])
        used_candidates.add(pair)
        key = (candidate["source"], candidate["target"], "related")
        if key not in existing:
            confidence = min(0.45, max(0.25, float(candidate.get("score", 0.0)) * 0.5))
            bridged.append({
                "source": candidate["source"],
                "target": candidate["target"],
                "edge_type": "related",
                "evidence": (
                    _clean_text(candidate.get("evidence"))
                    or f"Conservative relation candidate: {candidate.get('reason', 'ontology/text co-occurrence')}"
                ),
                "confidence": round(confidence, 3),
                "weight": round(0.2 + confidence * 0.8, 3),
            })
            existing.add(key)
    return bridged


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
                "source_term": _clean_text(item.get("source_term")),
                "source_ref": _clean_text(item.get("source_ref")) or None,
            }
        )
    return nodes


async def extract_relations(
    content: str,
    *,
    source_title: str,
    nodes: list[dict[str, Any]],
    relation_candidates: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if not nodes:
        return []
    prompt = RELATION_PROMPT.format(
        source_title=source_title,
        nodes=_format_nodes(nodes),
        candidates=_format_relation_candidates(relation_candidates or [], nodes),
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
    node_by_id = {node["id"]: node for node in nodes}
    candidate_by_pair: dict[tuple[str, str], dict[str, Any]] = {}
    for candidate in relation_candidates or []:
        candidate_by_pair[(candidate["source"], candidate["target"])] = candidate
        candidate_by_pair.setdefault(
            (candidate["target"], candidate["source"]), candidate
        )

    edges: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in data["edges"]:
        if not isinstance(item, dict):
            continue
        source = aliases.get(_clean_text(item.get("source")).lower())
        target = aliases.get(_clean_text(item.get("target")).lower())
        if not source or not target or source not in valid_ids or target not in valid_ids:
            continue
        source_node = next(node for node in nodes if node["id"] == source)
        target_node = next(node for node in nodes if node["id"] == target)
        edge_type = _normalize_edge_type(item.get("type"))
        if edge_type == "related":
            # The ontology candidate is more specific than a generic model
            # fallback. Upgrade only when the model confirmed the same pair.
            candidate = candidate_by_pair.get((source, target))
            candidate_type = _normalize_edge_type(candidate.get("edge_type")) if candidate else "related"
            if candidate_type != "related":
                if _relation_direction_is_valid(source_node, target_node, candidate_type):
                    edge_type = candidate_type
                elif _relation_direction_is_valid(target_node, source_node, candidate_type):
                    source, target = target, source
                    source_node, target_node = target_node, source_node
                    edge_type = candidate_type
        if not _relation_direction_is_valid(source_node, target_node, edge_type):
            if _relation_direction_is_valid(target_node, source_node, edge_type):
                source, target = target, source
                source_node, target_node = target_node, source_node
            else:
                # A specific edge with impossible endpoints is semantically
                # unsafe. Keep the connection only as a weak related edge.
                edge_type = "related"
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
    relation_candidates = build_relation_candidates(content, nodes)
    edges = await extract_relations(
        content,
        source_title=source_title,
        nodes=nodes,
        relation_candidates=relation_candidates,
    )
    edges = _bridge_disconnected_components(nodes, edges, relation_candidates)
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
        "relation_candidates": relation_candidates,
        "stats": {
            "node_count": len(enriched_nodes),
            "edge_count": len(edges),
            "node_types": sorted({node["node_type"] for node in enriched_nodes}),
            "edge_types": sorted({edge["edge_type"] for edge in edges}),
            "relation_candidate_count": len(relation_candidates),
            "relation_candidate_coverage": (
                len({
                    item["source"] for item in relation_candidates
                } | {
                    item["target"] for item in relation_candidates
                }) / len(enriched_nodes)
                if enriched_nodes else 0.0
            ),
            "connected_components": len(_graph_components(enriched_nodes, edges)),
            "isolated_node_count": sum(
                1 for component in _graph_components(enriched_nodes, edges)
                if len(component) == 1
            ),
        },
    }
