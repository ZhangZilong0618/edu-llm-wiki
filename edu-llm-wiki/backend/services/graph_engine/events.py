"""In-process pub/sub for learning-graph events.

A tiny synchronous topic bus. The HTTP layer (graph + learning routes) uses
it to publish domain events; the SSE endpoint and the frontend EventSource
hook consume them. Events are also persisted to the ``graph_events`` SQLite
table by the store, so a reconnecting client can replay history within the
``replay_window_seconds`` window.
"""
from __future__ import annotations
import time
from dataclasses import dataclass, field
from typing import Any, Callable, List
@dataclass
class _Subscriber:
    queue: List[dict] = field(default_factory=list)
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
        sub(event)
    return event
def subscribe() -> _Subscriber:
    sub = _Subscriber()
    _SUBSCRIBERS.append(sub)
    return sub
def unsubscribe(sub: _Subscriber) -> None:
    if sub in _SUBSCRIBERS:
        _SUBSCRIBERS.remove(sub)
def drain(sub: _Subscriber) -> list[dict]:
    out = list(sub.queue)
    sub.queue.clear()
    return out
