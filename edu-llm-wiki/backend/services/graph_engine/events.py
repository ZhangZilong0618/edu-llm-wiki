"""In-process pub/sub for learning-graph events.

A tiny synchronous topic bus. The HTTP layer (graph + learning routes) uses
it to publish domain events; the SSE endpoint and the frontend EventSource
hook consume them. Events are also persisted to the ``graph_events`` SQLite
table by the store, so a reconnecting client can replay history within the
``replay_window_seconds`` window.
"""
from __future__ import annotations
import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, List, Optional
@dataclass
class _Subscriber:
    queue: List[dict] = field(default_factory=list)
    project_id: str = ""
    last_seen_id: int = 0
    def __call__(self, event: dict) -> None:
        self.queue.append(event)
_SUBSCRIBERS: list[_Subscriber] = []
def publish(event_type: str, project_id: str, **payload: Any) -> dict:
    event = {
        "event_type": event_type,
        "project_id": project_id,
        "payload": payload,
        "created_at": time.time(),
    }
    for sub in _SUBSCRIBERS:
        if sub.project_id and sub.project_id != project_id:
            continue
        sub(event)
    return event
def subscribe(project_id: str = "") -> _Subscriber:
    sub = _Subscriber(project_id=project_id)
    _SUBSCRIBERS.append(sub)
    return sub
def unsubscribe(sub: _Subscriber) -> None:
    if sub in _SUBSCRIBERS:
        _SUBSCRIBERS.remove(sub)
def drain(sub: _Subscriber) -> list[dict]:
    out = list(sub.queue)
    sub.queue.clear()
    return out
def replay(project_id: str, since_id: int = 0) -> list[dict]:
    """Return persisted events newer than ``since_id`` for ``project_id``.

    Reads from the SQLite store (best-effort) so a reconnecting SSE client
    can pick up where it left off. Returns an empty list if the store is
    unavailable (e.g. during early startup) rather than raising.
    """
    try:
        from services.graph_store import recent_events
        rows = recent_events(project_id, limit=200)
    except Exception:
        return []
    out: list[dict] = []
    for r in rows:
        if int(r.get("id", 0)) <= int(since_id):
            continue
        out.append(
            {
                "id": int(r.get("id", 0)),
                "event_type": r.get("event_type", ""),
                "project_id": r.get("project_id", project_id),
                "payload": r.get("payload") or {},
                "created_at": r.get("created_at", 0.0),
            }
        )
    out.reverse()  # replay oldest-first so the client can append
    return out
async def next(project_id: str, timeout: float = 15.0) -> Optional[dict]:
    """Block until a new event for ``project_id`` is published or timeout.

    Used by the SSE endpoint's long-poll loop. Falls back to a sleep so
    the loop can heartbeat.
    """
    sub = subscribe(project_id=project_id)
    try:
        deadline = time.monotonic() + timeout
        while True:
            for event in list(sub.queue):
                if event.get("project_id") != project_id:
                    continue
                if int(event.get("id", 0)) <= int(sub.last_seen_id):
                    continue
                sub.last_seen_id = int(event.get("id", sub.last_seen_id))
                return event
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            await asyncio.sleep(min(0.5, remaining))
    finally:
        unsubscribe(sub)
