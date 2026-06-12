"""API routes for the learning graph.

Three v1 endpoints (``GET /api/graph``, ``/neighborhood/{id}``,
``/insights``) are kept compatible but now read from the persistent graph
store, which means a single rebuild on ingest vs a rebuild on every
request. New v2 endpoints cover mastery, learning paths, and an SSE event
stream.

The store layer owns persistence; this file owns HTTP wiring only.
"""

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from models.graph import (
    GraphData,
    GraphEvent as GraphEventModel,
    LearningPathResponse,
)
from services.graph_engine import build_graph, get_node_neighborhood
from services.graph_engine import events as graph_events
from services.graph_engine.paths import compute_learning_path
from services.graph_store import (
    get_nodes as store_get_nodes,
    get_edges as store_get_edges,
    get_communities as store_get_communities,
    get_insights as store_get_insights,
    get_mastery as store_get_mastery,
    record_exposure as store_record_exposure,
    record_attempt as store_record_attempt,
    record_graph_event,
    ensure_schema as store_ensure_schema,
)
from services.mastery import learner_state_summary, record_attempt, record_confidence, queue_for_user

router = APIRouter(prefix="/api/graph", tags=["graph"])


@router.on_event("startup")
async def _warm_graph_store() -> None:
    """Create the SQLite schema on first request.

    ``projects_dir`` is the only thing the store needs to bootstrap. We
    call ``ensure_schema`` for every project we know about at startup so the
    tables are present before the first rebuild.
    """
    from config import settings
    from pathlib import Path

    projects_root = Path(settings.projects_dir)
    if not projects_root.exists():
        return
    for project_dir in projects_root.iterdir():
        if project_dir.is_dir():
            store_ensure_schema(project_dir.name)


@router.get("", response_model=GraphData)
async def get_graph(
    project_id: str = Query("default"),
    rebuild: bool = Query(False, description="Force a full rebuild instead of reading the store."),
) -> GraphData:
    """Return the full graph. Reads from the store by default; pass
    ``?rebuild=true`` to force a full re-derivation (e.g. after editing
    many pages at once).
    """
    if rebuild:
        graph = build_graph(project_id=project_id, force=True)
    else:
        nodes = store_get_nodes(project_id)
        edges = store_get_edges(project_id)
        if not nodes or (len(nodes) > 1 and not edges):
            # New/imported projects can have wiki pages before graph.sqlite has
            # been populated (for example if ingest graph rebuild was skipped).
            # Build once here so the UI does not show an empty graph/path for a
            # project that already has usable wiki content.
            graph = build_graph(project_id=project_id)
        else:
            graph = {
                "nodes": nodes,
                "edges": edges,
                "communities": store_get_communities(project_id),
                "insights": store_get_insights(project_id),
            }
    return GraphData(**graph)


@router.get("/neighborhood/{node_id}")
async def get_neighborhood(
    node_id: str,
    depth: int = Query(1, ge=1, le=3),
    project_id: str = Query("default"),
) -> dict:
    """Get a node and its neighbours up to ``depth`` hops, anchored at the
    store snapshot so it benefits from the same incremental indexing.
    """
    return get_node_neighborhood(node_id, depth, project_id=project_id)


@router.get("/insights")
async def get_insights(project_id: str = Query("default")) -> list[dict]:
    """Get graph insights only, served from the persistent store."""
    return store_get_insights(project_id)


# ---------------------------------------------------------------------------
# v2 endpoints — learning path, mastery, events
# ---------------------------------------------------------------------------


@router.get("/learning-path/{node_id}", response_model=LearningPathResponse)
async def get_learning_path(
    node_id: str,
    user_id: str = Query("default"),
    project_id: str = Query("default"),
    max_steps: int = Query(8, ge=1, le=20),
) -> LearningPathResponse:
    """Produce an ordered study track from a learner's current mastery to
    ``node_id``. Steps are prerequisite nodes the learner has not yet
    reached the ``proficient`` level on.
    """
    return compute_learning_path(
        target=node_id,
        edges=store_get_edges(project_id),
        nodes_by_id={n["id"]: n for n in store_get_nodes(project_id)},
        max_steps=max_steps,
    )


@router.get("/mastery", response_model=list)
async def get_mastery_summary(
    user_id: str = Query("default"),
    project_id: str = Query("default"),
) -> list[dict]:
    """Per-node mastery records for the user (consumed by the graph view)."""
    return store_mastery_summary(project_id=project_id, user_id=user_id) if False else _list_mastery(project_id, user_id)


def _list_mastery(project_id: str, user_id: str) -> list[dict]:
    # The store exposes a different name; bridge to keep the route simple.
    from services.graph_store import execute
    rows = execute(
        project_id,
        "SELECT node_id, state AS level, score, attempts AS exposures, "
        "last_seen_at AS last_exposure_at FROM node_mastery WHERE user_id=?",
        (user_id,),
    )
    return [dict(r) for r in rows]


@router.get("/mastery/{node_id}")
async def get_node_mastery(
    node_id: str,
    user_id: str = Query("default"),
    project_id: str = Query("default"),
) -> dict:
    """Return the mastery record for a single node."""
    record = store_get_mastery(project_id=project_id, user_id=user_id, node_id=node_id)
    return record or {"node_id": node_id, "level": "new", "score": 0.0}


@router.post("/mastery/{node_id}/exposure")
async def post_node_exposure(
    node_id: str,
    user_id: str = Query("default"),
    project_id: str = Query("default"),
) -> dict:
    """Mark the learner as having seen ``node_id`` (page open, chat
    referenced, etc.). Promotes ``new`` → ``exposed``.
    """
    level = store_record_exposure(project_id=project_id, user_id=user_id, node_id=node_id)
    record_graph_event(
        project_id=project_id,
        event_type="node_exposed",
        payload={"node_id": node_id, "level": level},
    )
    return {"node_id": node_id, "level": level}


@router.post("/mastery/{node_id}/attempt")
async def post_node_attempt(
    node_id: str,
    score: float = Query(..., ge=0.0, le=1.0),
    user_id: str = Query("default"),
    project_id: str = Query("default"),
) -> dict:
    """Record a graded attempt against ``node_id``. ``score`` is the
    normalised 0..1 result returned by the grader.
    """
    level = store_record_attempt(
        project_id=project_id,
        user_id=user_id,
        node_id=node_id,
        score=score,
    )
    record_graph_event(
        project_id=project_id,
        event_type="node_attempted",
        payload={"node_id": node_id, "score": score, "level": level},
    )
    return {"node_id": node_id, "level": level, "score": score}


@router.get("/events/stream")
async def stream_graph_events(
    project_id: str = Query("default"),
    last_event_id: int = Query(0, ge=0),
) -> StreamingResponse:
    """Server-Sent Events stream of learning-graph mutations.

    The response begins by replaying any events newer than ``last_event_id``
    (so a reconnecting client can pick up where it left off) and then keeps
    the connection open, pushing new events as they are recorded.
    """
    async def event_source() -> AsyncIterator[bytes]:
        for event in graph_events.replay(project_id=project_id, since_id=last_event_id):
            model = GraphEventModel(
                id=event["id"],
                project_id=event["project_id"],
                event_type=event["event_type"],
                payload=event.get("payload") or {},
                created_at=event["created_at"],
            )
            yield f"id: {model.id}\nevent: {model.event_type}\ndata: {model.model_dump_json()}\n\n".encode("utf-8")
        sub = graph_events.subscribe()
        try:
            # Long-poll loop. In production this would be replaced with a
            # proper async queue; the synchronous in-memory bus is sufficient
            # for a single-process dev server.
            while True:
                events = [
                    event
                    for event in graph_events.drain(sub)
                    if event.get("project_id") == project_id
                ]
                if not events:
                    yield b": ping\n\n"
                    await asyncio.sleep(15)
                    continue
                for event in events:
                    model = GraphEventModel(
                        id=0,
                        project_id=event["project_id"],
                        event_type=event["event_type"],
                        payload=event.get("payload") or {},
                        created_at=event["created_at"],
                    )
                    yield f"event: {model.event_type}\ndata: {model.model_dump_json()}\n\n".encode("utf-8")
        finally:
            graph_events.unsubscribe(sub)

    return StreamingResponse(event_source(), media_type="text/event-stream")


# ============================================================================
# v3: learner-facing endpoints
# ============================================================================

@router.get("/learning/state")
async def get_learner_state(
    user_id: str = Query("default"),
    project_id: str = Query("default"),
) -> dict:
    """8-dim learner state summary (BKT p_known avg, weak KCs, etc.)."""
    from services import mastery
    return mastery.learner_state_summary(project_id=project_id, user_id=user_id)


@router.get("/learning/schedule")
async def get_learning_schedule(
    user_id: str = Query("default"),
    project_id: str = Query("default"),
    limit: int = Query(10, ge=1, le=50),
) -> list[dict]:
    """SR review queue ordered by due_at."""
    from services import mastery
    return mastery.queue_for_user(project_id=project_id, user_id=user_id, limit=limit)


@router.post("/learning/review")
async def post_learning_review(
    payload: dict,
    user_id: str = Query("default"),
    project_id: str = Query("default"),
) -> dict:
    """Submit a single review attempt; updates BKT + SM-2 + confidence."""
    from services import mastery
    kc_id = payload.get("kc_id") or payload.get("node_id")
    score = float(payload.get("score", 0.0))
    max_score = float(payload.get("max_score", 1.0)) or 1.0
    confidence = payload.get("confidence")
    if confidence is not None:
        confidence = int(confidence)
    new_state = mastery.record_attempt(
        project_id=project_id,
        user_id=user_id,
        kc_id=str(kc_id),
        score=score,
        max_score=max_score,
        confidence=confidence,
    )
    return new_state


@router.get("/learning/insights")
async def get_learning_insights(
    user_id: str = Query("default"),
    project_id: str = Query("default"),
) -> list[dict]:
    """Learner-aware insights: frontier / stale / readiness / transfer / misc cluster."""
    from services.graph_engine import generate_learner_insights
    from services.graph_engine import build_graph as _bg
    from services import mastery
    graph = _bg(project_id=project_id)
    state = mastery.learner_state_summary(project_id=project_id, user_id=user_id)
    return generate_learner_insights(
        graph["nodes"],
        graph["edges"],
        graph.get("communities") or [],
        state,
    )


# ============================================================================
# v3: learner-facing endpoints
# ============================================================================

from services.graph_engine import generate_learner_insights
from services.learning import error_model


@router.get("/learning/state")
async def get_learner_state(
    user_id: str = Query("default"),
    project_id: str = Query("default"),
) -> dict:
    """The 8-dim learner state used by the v3 learning panel."""
    return learner_state_summary(project_id=project_id, user_id=user_id)


@router.get("/learning/schedule")
async def get_review_schedule(
    user_id: str = Query("default"),
    project_id: str = Query("default"),
    limit: int = Query(10, ge=1, le=50),
) -> list[dict]:
    """Return the spaced-repetition review queue for ``user_id``."""
    return queue_for_user(project_id=project_id, user_id=user_id, limit=limit)


@router.post("/learning/review")
async def post_review(
    payload: dict,
    user_id: str = Query("default"),
    project_id: str = Query("default"),
) -> dict:
    """Record a review answer.

    ``payload`` carries ``kc_id`` (or ``node_id`` for backwards compat),
    ``score`` (0..1) and optional ``confidence`` (1..5).
    """
    kc_id = payload.get("kc_id") or payload.get("node_id") or ""
    if not kc_id:
        return {"ok": False, "error": "kc_id required"}
    score = float(payload.get("score", 0.0))
    confidence = payload.get("confidence")
    expected = payload.get("expected", "")
    response = payload.get("response", "")
    misconceptions = error_model.classify_error(response, expected) if expected else []
    record_attempt(
        project_id=project_id,
        user_id=user_id,
        node_id=kc_id,
        score=score,
    )
    if confidence is not None:
        record_confidence(
            project_id=project_id,
            user_id=user_id,
            kc_id=kc_id,
            level=int(confidence),
            correct=score >= 0.6,
        )
    return {
        "ok": True,
        "kc_id": kc_id,
        "score": score,
        "misconceptions": misconceptions,
    }


@router.get("/learning/insights")
async def get_learner_insights(
    user_id: str = Query("default"),
    project_id: str = Query("default"),
) -> list[dict]:
    """Structural + learner-aware insights filtered to ``R7`` threshold."""
    state = learner_state_summary(project_id=project_id, user_id=user_id)
    graph = {
        "nodes": store_get_nodes(project_id),
        "edges": store_get_edges(project_id),
        "communities": store_get_communities(project_id),
    }
    return generate_learner_insights(graph, state)


# ============================================================================

# (end of routes/graph.py — v3 learner endpoints registered above)
