"""Learning path computation.

Walks prerequisite edges backwards from a target node and orders the
visited nodes so weak prerequisites float up first. The result is capped
to ``max_steps`` so the UI can render a clean linear track; any remaining
prereqs are returned in ``remaining`` for pagination.
"""

from __future__ import annotations

from collections import deque
from typing import Iterable


def compute_learning_path(
    target: str,
    edges: list[dict],
    nodes_by_id: dict[str, dict],
    mastery_map: dict[str, str] | None = None,
    mastery_scores: dict[str, float] | None = None,
    max_steps: int = 8,
) -> dict:
    """Return an ordered learning path from current mastery to ``target``.

    Parameters
    ----------
    target
        Node id the learner wants to reach.
    edges
        All edges in the project graph. Only ``prerequisite`` (and
        ``direct`` as a fallback) edges are followed.
    nodes_by_id
        Lookup of node metadata by id.
    mastery_map, mastery_scores
        Per-node mastery state from the mastery store. Missing entries
        default to ``new``/``0.0``.
    max_steps
        Cap on the number of steps returned in the first page.

    Returns
    -------
    ``{target, steps, remaining, estimated_total_minutes}`` where each step
    carries ``node_id, title, node_type, reason, mastery, score,
    estimated_minutes``.
    """
    mastery_map = mastery_map or {}
    mastery_scores = mastery_scores or {}

    if target not in nodes_by_id:
        return {
            "target": target,
            "steps": [],
            "remaining": [],
            "estimated_total_minutes": 0,
        }

    # Collect prerequisite neighbours (target depends on prereq, so we walk
    # edges where target is the downstream side).
    prereq_for: dict[str, set[str]] = {}
    for e in edges:
        if e.get("edge_type") not in {"prerequisite", "direct"}:
            continue
        prereq_for.setdefault(e["target"], set()).add(e["source"])
        prereq_for.setdefault(e["source"], set())  # ensure key exists

    # BFS backwards from target; ``rank`` = how many prerequisite hops
    # away from the target.
    ranks: dict[str, int] = {target: 0}
    queue: deque[str] = deque([target])
    while queue:
        cur = queue.popleft()
        rank = ranks[cur] + 1
        for pre in prereq_for.get(cur, set()):
            if pre not in nodes_by_id:
                continue
            if pre in ranks and ranks[pre] <= rank:
                continue
            ranks[pre] = rank
            queue.append(pre)

    # Exclude the target itself from the path; it is the destination, not
    # a step.
    candidate_ids = [nid for nid in ranks if nid != target]
    if not candidate_ids:
        return {
            "target": target,
            "steps": [],
            "remaining": [],
            "estimated_total_minutes": 0,
        }

    # Sort: deeper prereqs first, then weakest mastery, then alphabetical
    # id for stable ordering. This pushes foundational concepts to the top
    # of the path and floats weak spots to the front of the queue.
    def sort_key(nid: str) -> tuple[int, float, str]:
        level = mastery_map.get(nid, "new")
        return (ranks[nid], _mastery_rank(level), nid)

    candidate_ids.sort(key=sort_key)
    ordered = candidate_ids[:max_steps]
    remaining = [Candidate(c, ranks[c]) for c in candidate_ids[max_steps:]]

    steps = [
        {
            "node_id": nid,
            "title": nodes_by_id[nid].get("label", nid),
            "node_type": nodes_by_id[nid].get("node_type", "unknown"),
            "reason": _reason_text(nid, target, ranks),
            "mastery": mastery_map.get(nid, "new"),
            "score": mastery_scores.get(nid, 0.0),
            "estimated_minutes": _estimate_minutes(nid, nodes_by_id, edges),
        }
        for nid in ordered
    ]
    return {
        "target": target,
        "steps": steps,
        "remaining": [c.target for c in remaining],
        "estimated_total_minutes": sum(s["estimated_minutes"] for s in steps),
    }


def _mastery_rank(level: str) -> int:
    return {
        "mastered": 4,
        "proficient": 3,
        "learning": 2,
        "exposed": 1,
        "new": 0,
    }.get(level, 0)


def _reason_text(nid: str, target: str, ranks: dict[str, int]) -> str:
    hop = ranks.get(nid, 0)
    if hop <= 1:
        return f"前置知识：理解 {nid} 后才能继续 {target}"
    return f"前置链第 {hop} 层：补齐 {nid} 以打通 {target} 的学习路径"


def _estimate_minutes(nid: str, nodes_by_id: dict, edges: Iterable[dict]) -> int:
    """Rough time estimate: 5 min base + 1 min per prerequisite link."""
    base = 5
    extra = sum(1 for e in edges if e.get("target") == nid and e.get("edge_type") in {"prerequisite", "direct"})
    node = nodes_by_id.get(nid, {})
    estimated = node.get("estimated_minutes")
    if isinstance(estimated, (int, float)) and estimated > 0:
        return int(estimated)
    return base + extra


class Candidate:
    __slots__ = ("target", "rank")

    def __init__(self, target: str, rank: int) -> None:
        self.target = target
        self.rank = rank
