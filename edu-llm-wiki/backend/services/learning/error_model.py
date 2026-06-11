"""Misconception classification — Brown & Burton 1978.

We model misconceptions as a small taxonomy of tags that a domain expert
can extend. Classification is intentionally lightweight: the goal is not to
be a theorem prover, but to associate each wrong ans...g_error — conceptual gap, often a missing prerequisite
* careless — slip-like, LLM should report high confidence

The mapping is conservative: only assign a tag if at least one keyword in
its group appears in the response and there is at least one such keyword
absent from the expected answer.
"""

from __future__ import annotations

from collections import Counter
from typing import Iterable, List, Sequence, Tuple

GROUPS = {
    "off_by_one": ["+1", "+2", "-1", "n+1", "边界", "越界"],
    "misread_sign": ["负", "正", "符号", "sign", "-"],
    "conflated_terms": ["混淆", "以为是", "其实不是", "confuse"],
    "missing_step": ["跳过", "直接得到", "skip", "obvious"],
    "wrong_unit": ["单位", "degree", "弧度", "radian", "米", "厘米"],
    "procedural_misuse": ["公式", "formula", "定理", "axiom"],
    "careless": ["忘了", "不小心", "手误", "typo"],
    "conceptual_gap": ["不知道", "不清楚", "不明白", "why"],
}


def classify_error(response: str, expected: str) -> List[str]:
    """Return a list of misconception tags. May be empty if the response is correct."""
    if not response or not expected:
        return []
    if response.strip() == expected.strip():
        return []
    resp_l = response.lower()
    exp_l = expected.lower()
    tags: list[str] = []
    for tag, keywords in GROUPS.items():
        hits_resp = sum(1 for kw in keywords if kw.lower() in resp_l)
        hits_exp = sum(1 for kw in keywords if kw.lower() in exp_l)
        if hits_resp >= 1 and hits_resp > hits_exp:
            tags.append(tag)
    return tags


def cluster_traces(traces: Iterable[Tuple[str, str]]) -> list[dict]:
    """Aggregate traces by tag → list of {tag, count, examples}."""
    bag: dict[str, list[str]] = {}
    for tag, response in traces:
        if not tag:
            continue
        bag.setdefault(tag, []).append(response[:80])
    return sorted(
        (
            {"tag": tag, "count": len(examples), "examples": examples[:3]}
            for tag, examples in bag.items()
        ),
        key=lambda x: -x["count"],
    )


def top_misconception(traces: Sequence[Tuple[str, str]]) -> str | None:
    """Return the most frequent misconception tag, or None if no traces."""
    counts = Counter(tag for tag, _ in traces if tag)
    if not counts:
        return None
    return counts.most_common(1)[0][0]
