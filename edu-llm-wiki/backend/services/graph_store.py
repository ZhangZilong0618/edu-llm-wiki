"""Persistent SQLite-backed graph store for the learning-graph v2.

One SQLite file per project lives at
``<settings.projects_dir>/<project_id>/graph.sqlite``. The store exposes
synchronous, thread-safe helpers that build / read / incrementally update
the graph based on wiki content + ingest-engine output.

Schema (created lazily on first connect):

- ``graph_nodes``       -- one row per wiki page; ``content_hash`` + ``mtime``
                           drive incremental updates.
- ``graph_edges``       -- directed edges with type / weight / source.
- ``graph_communities`` -- cached Louvain partition + label + cohesion.
- ``graph_insights``    -- cached AI / structural insights (knowledge_gap,
                           bridge, surprising_connection, isolated).
- ``node_mastery``      -- per-user mastery state machine.
- ``graph_events``      -- append-only event log (mastery_change, node_added,
                           edge_added, insight, gap).
- ``graph_snapshots``   -- versioned JSON snapshots for diff/rollback.

This module is intentionally framework-free — it owns the file and exposes
plain Python functions. Higher layers (graph_engine, routes) compose it.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator

from config import settings
from storage.wiki_store import list_wiki_pages, read_wiki_page, validate_project_id

# ---------------------------------------------------------------------------
# Schema & version
# ---------------------------------------------------------------------------

SCHEMA_VERSION = 2

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS graph_nodes (
    project_id        TEXT NOT NULL,
    node_id           TEXT NOT NULL,
    page_path         TEXT NOT NULL,
    title             TEXT,
    type              TEXT,
    bloom_level       TEXT,
    difficulty        INTEGER,
    estimated_minutes REAL,
    parent_concept    TEXT,
    tags_json         TEXT,
    community_id      INTEGER,
    degree_in         INTEGER DEFAULT 0,
    degree_out        INTEGER DEFAULT 0,
    content_hash      TEXT,
    mtime             REAL,
    metadata_json     TEXT,
    created_at        REAL,
    updated_at        REAL,
    PRIMARY KEY (project_id, node_id)
);
CREATE INDEX IF NOT EXISTS idx_nodes_type   ON graph_nodes(project_id, type);
CREATE INDEX IF NOT EXISTS idx_nodes_parent ON graph_nodes(project_id, parent_concept);
CREATE INDEX IF NOT EXISTS idx_nodes_mtime  ON graph_nodes(project_id, mtime);

CREATE TABLE IF NOT EXISTS graph_edges (
    project_id TEXT NOT NULL,
    edge_id    TEXT NOT NULL,    -- sha1(src|trg|type)
    source     TEXT NOT NULL,
    target     TEXT NOT NULL,
    edge_type  TEXT NOT NULL,    -- prerequisite|derives|applies_to|teaches|
                                 -- enables|related
    weight     REAL DEFAULT 1.0,
    origin     TEXT,             -- llm|wikilink|frontmatter|inferred
    evidence   TEXT,
    metadata_json TEXT,
    created_at REAL,
    updated_at REAL,
    PRIMARY KEY (project_id, edge_id)
);
CREATE INDEX IF NOT EXISTS idx_edges_src ON graph_edges(project_id, source);
CREATE INDEX IF NOT EXISTS idx_edges_tgt ON graph_edges(project_id, target);
CREATE INDEX IF NOT EXISTS idx_edges_type ON graph_edges(project_id, edge_type);

CREATE TABLE IF NOT EXISTS graph_communities (
    project_id    TEXT NOT NULL,
    community_id  INTEGER NOT NULL,
    label         TEXT,
    cohesion      REAL,
    member_count  INTEGER,
    top_node      TEXT,
    member_nodes_json TEXT,
    updated_at    REAL,
    PRIMARY KEY (project_id, community_id)
);

CREATE TABLE IF NOT EXISTS graph_insights (
    project_id   TEXT NOT NULL,
    insight_id   TEXT NOT NULL,
    insight_type TEXT NOT NULL,    -- knowledge_gap|bridge|surprising_connection|isolated
    title        TEXT,
    description  TEXT,
    node_ids_json TEXT,
    score        REAL DEFAULT 0,
    updated_at   REAL,
    PRIMARY KEY (project_id, insight_id)
);

CREATE TABLE IF NOT EXISTS node_mastery (
    project_id   TEXT NOT NULL,
    user_id      TEXT NOT NULL,
    node_id      TEXT NOT NULL,
    state        TEXT NOT NULL,    -- unseen|exposed|attempted|partial|mastered
    score        REAL DEFAULT 0,   -- 0..1
    attempts     INTEGER DEFAULT 0,
    successes    INTEGER DEFAULT 0,
    last_seen_at REAL,
    next_review_at REAL,
    metadata_json TEXT,
    PRIMARY KEY (project_id, user_id, node_id)
);
CREATE INDEX IF NOT EXISTS idx_mastery_user ON node_mastery(project_id, user_id, state);

CREATE TABLE IF NOT EXISTS graph_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    event_type TEXT NOT NULL,      -- node_added|edge_added|insight|mastery_change|gap
    payload_json TEXT,
    created_at REAL
);
CREATE INDEX IF NOT EXISTS idx_events_proj_time ON graph_events(project_id, created_at DESC);

CREATE TABLE IF NOT EXISTS graph_snapshots (
    snapshot_id TEXT NOT NULL,
    project_id  TEXT NOT NULL,
    label       TEXT,
    snapshot_json TEXT,
    created_at  REAL,
    PRIMARY KEY (project_id, snapshot_id)
);


-- v3 pedagogy tables (Corbett & Anderson 1995 BKT, Wozniak SM-2,
-- Brown & Burton 1978 misconception, Karpicke confidence)

CREATE TABLE IF NOT EXISTS bkt_params (
    project_id TEXT NOT NULL,
    user_id    TEXT NOT NULL,
    kc_id      TEXT NOT NULL,    -- matches graph_nodes.node_id (KC == node for now)
    p_known    REAL DEFAULT 0.1, -- P(L)
    p_t        REAL DEFAULT 0.2, -- P(T) — learning transition
    p_g        REAL DEFAULT 0.2, -- P(G) — guess on un-mastered
    p_s        REAL DEFAULT 0.1, -- P(S) — slip on mastered
    last_obs   REAL,
    obs_n      INTEGER DEFAULT 0,
    PRIMARY KEY (project_id, user_id, kc_id)
);

CREATE TABLE IF NOT EXISTS sr_schedule (
    project_id   TEXT NOT NULL,
    user_id      TEXT NOT NULL,
    kc_id        TEXT NOT NULL,
    ef           REAL DEFAULT 2.5,   -- easiness factor (Wozniak)
    interval_days INTEGER DEFAULT 0, -- days until next due
    reps         INTEGER DEFAULT 0,
    quality_avg  REAL DEFAULT 0.0,
    due_at       REAL NOT NULL,
    last_review  REAL,
    PRIMARY KEY (project_id, user_id, kc_id)
);
CREATE INDEX IF NOT EXISTS idx_sr_due ON sr_schedule(project_id, user_id, due_at);

CREATE TABLE IF NOT EXISTS misconception_taxonomy (
    project_id      TEXT NOT NULL,
    misconception_id TEXT NOT NULL,
    label           TEXT NOT NULL,
    description     TEXT,
    canonical       TEXT,         -- the misconception text / pattern
    created_at      REAL,
    PRIMARY KEY (project_id, misconception_id)
);

CREATE TABLE IF NOT EXISTS misconception_traces (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id      TEXT NOT NULL,
    user_id         TEXT NOT NULL,
    kc_id           TEXT NOT NULL,
    misconception_tag TEXT,
    response_text   TEXT,
    matched_pattern TEXT,
    question_id     TEXT,
    created_at      REAL
);
CREATE INDEX IF NOT EXISTS idx_mis_user ON misconception_traces(project_id, user_id);

CREATE TABLE IF NOT EXISTS attempts_raw (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    user_id    TEXT NOT NULL,
    kc_id      TEXT NOT NULL,
    question_id TEXT,
    correct    INTEGER,
    score      REAL,
    max_score  REAL,
    confidence INTEGER,
    latency_ms INTEGER,
    hint_ladder INTEGER,
    ts         REAL
);
CREATE INDEX IF NOT EXISTS idx_attempts_user_kc ON attempts_raw(project_id, user_id, kc_id, ts DESC);

CREATE TABLE IF NOT EXISTS confidence_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    user_id    TEXT NOT NULL,
    kc_id      TEXT NOT NULL,
    confidence INTEGER,    -- 1..5
    correct    INTEGER,    -- 0/1
    residual   REAL,       -- confidence/5 − correct, the overconfidence gap
    ts         REAL
);
CREATE INDEX IF NOT EXISTS idx_conf_user ON confidence_log(project_id, user_id, ts DESC);

CREATE TABLE IF NOT EXISTS learning_state (
    project_id           TEXT NOT NULL,
    user_id              TEXT NOT NULL,
    p_known_avg          REAL,
    weak_kcs_json        TEXT,
    misconception_ids_json TEXT,
    transfer_json        TEXT,
    overconfidence_gap   REAL,
    readiness            REAL,
    sr_due_today         INTEGER,
    decay_risk           REAL,
    last_computed_at     REAL,
    PRIMARY KEY (project_id, user_id)
);
"""

# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_connections: dict[str, sqlite3.Connection] = {}


def _db_path(project_id: str) -> Path:
    validate_project_id(project_id)
    return Path(settings.projects_dir) / project_id / "graph.sqlite"


@contextmanager
def connect(project_id: str) -> Iterator[sqlite3.Connection]:
    """Yield a per-project SQLite connection (cached, WAL, thread-safe)."""
    path = _db_path(project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    key = project_id
    with _lock:
        conn = _connections.get(key)
        if conn is None:
            conn = sqlite3.connect(
                path, check_same_thread=False, isolation_level=None
            )
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.row_factory = sqlite3.Row
            conn.executescript(_SCHEMA_SQL)
            conn.execute(
                "INSERT OR REPLACE INTO schema_meta(key, value) VALUES('version', ?)",
                (str(SCHEMA_VERSION),),
            )
            _connections[key] = conn
        yield conn


def close_all() -> None:
    with _lock:
        for conn in _connections.values():
            try:
                conn.close()
            except Exception:
                pass
        _connections.clear()


# ---------------------------------------------------------------------------
# Node id helpers
# ---------------------------------------------------------------------------

def make_node_id(project_id: str, page_path: str) -> str:
    """Stable hash of (project_id, page_path). Path = identity, no .md strip."""
    raw = f"{project_id}|{page_path}".encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:16]


def make_edge_id(source: str, target: str, edge_type: str) -> str:
    raw = f"{source}|{target}|{edge_type}".encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Diff-and-apply (incremental update from wiki)
# ---------------------------------------------------------------------------

def _content_hash(page: dict) -> str:
    blob = json.dumps(
        {
            "title": page.get("title", ""),
            "type": page.get("page_type", ""),
            "sources": page.get("sources", []),
            "tags": page.get("tags", []),
            "content": page.get("content", ""),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _now() -> float:
    return time.time()


def diff_and_apply(project_id: str) -> dict:
    """Reconcile graph_nodes with current wiki state.

    Returns a diff dict with ``added`` / ``updated`` / ``removed`` lists so
    callers can publish events. Idempotent and safe to call from any thread.
    """
    added: list[str] = []
    updated: list[str] = []
    removed: list[str] = []

    pages = list_wiki_pages(project_id=project_id)
    seen_paths: set[str] = set()

    with connect(project_id) as conn:
        # Existing nodes indexed by page_path.
        existing = {
            row["page_path"]: dict(row)
            for row in conn.execute(
                "SELECT * FROM graph_nodes WHERE project_id=?", (project_id,)
            )
        }

        for summary in pages:
            page = read_wiki_page(summary["path"], project_id=project_id)
            if not page:
                continue
            seen_paths.add(page["path"])
            page_path = page["path"]
            node_id = make_node_id(project_id, page_path)
            content_hash = _content_hash(page)
            mtime = Path(_db_path(project_id).parent / "wiki" / page_path).stat().st_mtime \
                if (_db_path(project_id).parent / "wiki" / page_path).exists() else _now()
            frontmatter = _extract_frontmatter(page)
            row = {
                "node_id": node_id,
                "page_path": page_path,
                "title": page.get("title") or summary.get("title") or "",
                "type": page.get("page_type") or summary.get("type") or "concept",
                "bloom_level": frontmatter.get("bloom_level"),
                "difficulty": frontmatter.get("difficulty"),
                "estimated_minutes": frontmatter.get("estimated_minutes"),
                "parent_concept": frontmatter.get("parent_concept"),
                "tags_json": json.dumps(frontmatter.get("tags") or [], ensure_ascii=False),
                "content_hash": content_hash,
                "mtime": mtime,
                "metadata_json": json.dumps(
                    {"sources": page.get("sources", [])}, ensure_ascii=False
                ),
                "updated_at": _now(),
            }
            prev = existing.get(page_path)
            if prev is None:
                _upsert_node(conn, project_id, row, created=True)
                added.append(node_id)
            elif prev.get("content_hash") != content_hash or prev.get("title") != row["title"]:
                _upsert_node(conn, project_id, row, created=False)
                updated.append(node_id)
            # unchanged → skip

        # Detect removed pages.
        for page_path, prev in existing.items():
            if page_path not in seen_paths:
                conn.execute(
                    "DELETE FROM graph_nodes WHERE project_id=? AND node_id=?",
                    (project_id, prev["node_id"]),
                )
                conn.execute(
                    "DELETE FROM graph_edges WHERE project_id=? AND (source=? OR target=?)",
                    (project_id, prev["node_id"], prev["node_id"]),
                )
                removed.append(prev["node_id"])

    return {"added": added, "updated": updated, "removed": removed}


def refresh_node_degrees(project_id: str) -> None:
    """Recompute degree_in / degree_out from the live ``graph_edges`` table.

    Must be called *after* edges have been persisted in the same
    reconciliation pass — apply_diff zeroes both columns, so a second
    pass once ``upsert_edges`` has run gives the correct connectivity
    counts that drive the Sigma node size.
    """
    with connect(project_id) as conn:
        conn.execute(
            """
            UPDATE graph_nodes
            SET degree_in = COALESCE((
                SELECT COUNT(*) FROM graph_edges
                WHERE graph_edges.project_id = graph_nodes.project_id
                  AND graph_edges.target = graph_nodes.node_id
            ), 0),
                degree_out = COALESCE((
                    SELECT COUNT(*) FROM graph_edges
                    WHERE graph_edges.project_id = graph_nodes.project_id
                      AND graph_edges.source = graph_nodes.node_id
                ), 0)
            WHERE project_id = ?
            """,
            (project_id,),
        )


def _extract_frontmatter(page: dict) -> dict[str, Any]:
    """Best-effort frontmatter extraction.

    The wiki_store doesn't expose `prerequisites`/`parent_concept` etc. on
    read, but we can re-parse from the body so diff_and_apply is
    independent of upstream changes.
    """
    content = page.get("content", "")
    if not content.startswith("---"):
        return {}
    end = content.find("\n---", 3)
    if end < 0:
        return {}
    block = content[3:end].strip()
    out: dict[str, Any] = {}
    current_key: str | None = None
    current_list: list[str] | None = None
    for raw in block.splitlines():
        line = raw.rstrip()
        if not line:
            continue
        if line.startswith("  - ") and current_list is not None:
            current_list.append(line[4:].strip().strip('"').strip("'"))
            continue
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            if value == "":
                current_list = []
                current_key = key
                out[key] = current_list
            elif value.startswith("[") and value.endswith("]"):
                inner = value[1:-1].strip()
                current_list = None
                current_key = None
                if not inner:
                    out[key] = []
                else:
                    out[key] = [
                        v.strip().strip('"').strip("'")
                        for v in inner.split(",")
                        if v.strip()
                    ]
            else:
                current_list = None
                current_key = None
                out[key] = _coerce_scalar(value)
    return out


def _coerce_scalar(value: str) -> Any:
    v = value.strip().strip('"').strip("'")
    if v.lower() in {"true", "false"}:
        return v.lower() == "true"
    try:
        if "." in v:
            return float(v)
        return int(v)
    except ValueError:
        return v


# ---------------------------------------------------------------------------
# Node / edge upserts
# ---------------------------------------------------------------------------

def _upsert_node(conn: sqlite3.Connection, project_id: str, row: dict, *, created: bool) -> None:
    now = _now()
    if created:
        conn.execute(
            """
            INSERT INTO graph_nodes(
                project_id, node_id, page_path, title, type,
                bloom_level, difficulty, estimated_minutes, parent_concept,
                tags_json, content_hash, mtime, metadata_json,
                created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                project_id, row["node_id"], row["page_path"], row["title"], row["type"],
                row["bloom_level"], row["difficulty"], row["estimated_minutes"], row["parent_concept"],
                row["tags_json"], row["content_hash"], row["mtime"], row["metadata_json"],
                now, row["updated_at"],
            ),
        )
    else:
        conn.execute(
            """
            UPDATE graph_nodes SET
                title=?, type=?, bloom_level=?, difficulty=?,
                estimated_minutes=?, parent_concept=?, tags_json=?,
                content_hash=?, mtime=?, metadata_json=?, updated_at=?
            WHERE project_id=? AND node_id=?
            """,
            (
                row["title"], row["type"], row["bloom_level"], row["difficulty"],
                row["estimated_minutes"], row["parent_concept"], row["tags_json"],
                row["content_hash"], row["mtime"], row["metadata_json"], row["updated_at"],
                project_id, row["node_id"],
            ),
        )


def upsert_edges(project_id: str, edges: Iterable[dict]) -> list[str]:
    """Insert/update edges from ingest or wikilink extraction.

    Each edge dict must have: ``source``, ``target``, ``edge_type``.
    Optional: ``weight``, ``origin``, ``evidence``, ``metadata``.
    Returns the list of edge_ids touched.
    """
    touched: list[str] = []
    with connect(project_id) as conn:
        for edge in edges:
            source = edge["source"]
            target = edge["target"]
            edge_type = edge["edge_type"]
            edge_id = make_edge_id(source, target, edge_type)
            now = _now()
            conn.execute(
                """
                INSERT INTO graph_edges(
                    project_id, edge_id, source, target, edge_type,
                    weight, origin, evidence, metadata_json,
                    created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(project_id, edge_id) DO UPDATE SET
                    weight=excluded.weight,
                    origin=excluded.origin,
                    evidence=excluded.evidence,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (
                    project_id, edge_id, source, target, edge_type,
                    float(edge.get("weight", 1.0)),
                    edge.get("origin", "inferred"),
                    edge.get("evidence", ""),
                    json.dumps(edge.get("metadata") or {}, ensure_ascii=False),
                    now, now,
                ),
            )
            touched.append(edge_id)
    return touched


def delete_orphan_edges(project_id: str, valid_nodes: set[str]) -> int:
    """Remove edges whose endpoints are no longer in the node set."""
    with connect(project_id) as conn:
        cur = conn.execute(
            "DELETE FROM graph_edges WHERE project_id=? AND (source NOT IN (SELECT node_id FROM graph_nodes WHERE project_id=?) OR target NOT IN (SELECT node_id FROM graph_nodes WHERE project_id=?))",
            (project_id, project_id, project_id),
        )
        return cur.rowcount


def clear_derived_graph(project_id: str) -> None:
    """Clear cached graph artifacts that are recomputed from wiki pages."""
    with connect(project_id) as conn:
        conn.execute("DELETE FROM graph_edges WHERE project_id=?", (project_id,))
        conn.execute("DELETE FROM graph_communities WHERE project_id=?", (project_id,))
        conn.execute("DELETE FROM graph_insights WHERE project_id=?", (project_id,))


# ---------------------------------------------------------------------------
# Read helpers (cheap, used by /api/graph)
# ---------------------------------------------------------------------------

def get_all_nodes(project_id: str) -> list[dict]:
    with connect(project_id) as conn:
        rows = conn.execute(
            "SELECT * FROM graph_nodes WHERE project_id=?", (project_id,)
        ).fetchall()
    out: list[dict] = []
    for r in rows:
        d = dict(r)
        # Map persistence row keys to the GraphNode Pydantic contract.
        degree = int(d.get("degree_in") or 0) + int(d.get("degree_out") or 0)
        # Log-scale so a hub (degree ~30) renders ~2x larger than a leaf
        # (degree 1) without dominating the canvas. Floor at 1 so every
        # node is at least the default Sigma radius. Stored as int to match
        # the Pydantic GraphNode contract.
        size = max(1, int(round(1.0 + math.log1p(max(degree, 0)) * 1.2)))
        out.append({
            "id": d.get("node_id") or d.get("id") or "",
            "label": d.get("title") or d.get("label") or d.get("node_id", ""),
            "node_type": d.get("type") or d.get("node_type") or "concept",
            "page_path": d.get("page_path", ""),
            "size": size,
            "community": d.get("community_id", -1) if d.get("community_id") is not None else -1,
            "metadata": {"content_hash": d.get("content_hash", "")},
            "bloom_level": d.get("bloom_level"),
            "difficulty": d.get("difficulty"),
            "estimated_minutes": d.get("estimated_minutes"),
            "parent_concept": d.get("parent_concept"),
            "tags": [],
            "mtime": d.get("mtime"),
        })
    return out


def get_all_edges(project_id: str) -> list[dict]:
    with connect(project_id) as conn:
        rows = conn.execute(
            "SELECT * FROM graph_edges WHERE project_id=?", (project_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_neighbors(project_id: str, node_id: str, depth: int = 1) -> list[dict]:
    """BFS up to ``depth`` hops; returns the list of edges traversed.

    Each returned edge dict has ``source`` / ``target`` (node_ids) and a
    ``depth`` key indicating how many hops from the start node.
    """
    depth = max(1, min(int(depth), 3))
    visited: set[str] = {node_id}
    frontier: set[str] = {node_id}
    collected: list[dict] = []
    with connect(project_id) as conn:
        for d in range(1, depth + 1):
            if not frontier:
                break
            placeholders = ",".join("?" for _ in frontier)
            params: list[Any] = [project_id, *frontier]
            rows = conn.execute(
                f"SELECT * FROM graph_edges WHERE project_id=? AND source IN ({placeholders})",
                params,
            ).fetchall()
            next_frontier: set[str] = set()
            for r in rows:
                edge = dict(r)
                edge["depth"] = d
                collected.append(edge)
                if edge["target"] not in visited:
                    visited.add(edge["target"])
                    next_frontier.add(edge["target"])
            frontier = next_frontier
    return collected


def get_community(project_id: str, community_id: int) -> list[str]:
    with connect(project_id) as conn:
        row = conn.execute(
            "SELECT member_nodes_json FROM graph_communities WHERE project_id=? AND community_id=?",
            (project_id, community_id),
        ).fetchone()
    if not row or not row["member_nodes_json"]:
        return []
    try:
        return json.loads(row["member_nodes_json"])
    except Exception:
        return []


def store_communities(project_id: str, communities: list[dict]) -> None:
    with connect(project_id) as conn:
        conn.execute("DELETE FROM graph_communities WHERE project_id=?", (project_id,))
        for c in communities:
            conn.execute(
                """
                INSERT INTO graph_communities(
                    project_id, community_id, label, cohesion,
                    member_count, top_node, member_nodes_json, updated_at
                ) VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    project_id,
                    int(c.get("id", 0)),
                    c.get("label", ""),
                    float(c.get("cohesion", 0.0)),
                    int(c.get("member_count", 0)),
                    c.get("top_node", ""),
                    json.dumps(c.get("members", []), ensure_ascii=False),
                    _now(),
                ),
            )


def store_insights(project_id: str, insights: list[dict]) -> None:
    with connect(project_id) as conn:
        conn.execute("DELETE FROM graph_insights WHERE project_id=?", (project_id,))
        for insight in insights:
            conn.execute(
                """
                INSERT INTO graph_insights(
                    project_id, insight_id, insight_type, title, description,
                    node_ids_json, score, updated_at
                ) VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    project_id,
                    insight.get("id") or hashlib.sha1(
                        f"{insight.get('insight_type')}|{insight.get('title','')}".encode()
                    ).hexdigest()[:16],
                    insight.get("insight_type", "knowledge_gap"),
                    insight.get("title", ""),
                    insight.get("description", ""),
                    json.dumps(insight.get("node_ids", []), ensure_ascii=False),
                    float(insight.get("score", 0.0)),
                    _now(),
                ),
            )


def load_communities(project_id: str) -> list[dict]:
    with connect(project_id) as conn:
        rows = conn.execute(
            "SELECT * FROM graph_communities WHERE project_id=? ORDER BY community_id",
            (project_id,),
        ).fetchall()
    out: list[dict] = []
    for r in rows:
        c = dict(r)
        try:
            c["members"] = json.loads(c.pop("member_nodes_json") or "[]")
        except Exception:
            c["members"] = []
        out.append(c)
    return out


def load_insights(project_id: str) -> list[dict]:
    with connect(project_id) as conn:
        rows = conn.execute(
            "SELECT * FROM graph_insights WHERE project_id=? ORDER BY score DESC",
            (project_id,),
        ).fetchall()
    out: list[dict] = []
    for r in rows:
        i = dict(r)
        try:
            i["node_ids"] = json.loads(i.pop("node_ids_json") or "[]")
        except Exception:
            i["node_ids"] = []
        out.append(i)
    return out


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

def record_event(project_id: str, event_type: str, payload: dict) -> int:
    with connect(project_id) as conn:
        cur = conn.execute(
            "INSERT INTO graph_events(project_id, event_type, payload_json, created_at) VALUES (?,?,?,?)",
            (project_id, event_type, json.dumps(payload, ensure_ascii=False), _now()),
        )
        return int(cur.lastrowid)


def recent_events(project_id: str, limit: int = 50, event_type: str | None = None) -> list[dict]:
    with connect(project_id) as conn:
        if event_type:
            rows = conn.execute(
                "SELECT * FROM graph_events WHERE project_id=? AND event_type=? ORDER BY id DESC LIMIT ?",
                (project_id, event_type, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM graph_events WHERE project_id=? ORDER BY id DESC LIMIT ?",
                (project_id, limit),
            ).fetchall()
    out: list[dict] = []
    for r in rows:
        e = dict(r)
        try:
            e["payload"] = json.loads(e.pop("payload_json") or "{}")
        except Exception:
            e["payload"] = {}
        out.append(e)
    return out


# ---------------------------------------------------------------------------
# Mastery
# ---------------------------------------------------------------------------

def get_mastery(project_id: str, user_id: str, node_id: str) -> dict | None:
    with connect(project_id) as conn:
        row = conn.execute(
            "SELECT * FROM node_mastery WHERE project_id=? AND user_id=? AND node_id=?",
            (project_id, user_id, node_id),
        ).fetchone()
    return dict(row) if row else None


def upsert_mastery(project_id: str, user_id: str, node_id: str, fields: dict) -> dict:
    existing = get_mastery(project_id, user_id, node_id) or {
        "state": "unseen",
        "score": 0.0,
        "attempts": 0,
        "successes": 0,
    }
    merged = {**existing, **fields}
    with connect(project_id) as conn:
        conn.execute(
            """
            INSERT INTO node_mastery(
                project_id, user_id, node_id, state, score,
                attempts, successes, last_seen_at, next_review_at, metadata_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(project_id, user_id, node_id) DO UPDATE SET
                state=excluded.state,
                score=excluded.score,
                attempts=excluded.attempts,
                successes=excluded.successes,
                last_seen_at=excluded.last_seen_at,
                next_review_at=excluded.next_review_at,
                metadata_json=excluded.metadata_json
            """,
            (
                project_id, user_id, node_id,
                merged.get("state", "unseen"),
                float(merged.get("score", 0.0)),
                int(merged.get("attempts", 0)),
                int(merged.get("successes", 0)),
                merged.get("last_seen_at"),
                merged.get("next_review_at"),
                json.dumps(merged.get("metadata") or {}, ensure_ascii=False),
            ),
        )
    return merged


def list_mastery(project_id: str, user_id: str) -> list[dict]:
    with connect(project_id) as conn:
        rows = conn.execute(
            "SELECT * FROM node_mastery WHERE project_id=? AND user_id=?",
            (project_id, user_id),
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Snapshots
# ---------------------------------------------------------------------------

def write_snapshot(project_id: str, label: str = "") -> str:
    snap_id = hashlib.sha1(f"{project_id}|{_now()}|{label}".encode()).hexdigest()[:16]
    payload = {
        "nodes": get_all_nodes(project_id),
        "edges": get_all_edges(project_id),
        "communities": load_communities(project_id),
        "insights": load_insights(project_id),
        "created_at": _now(),
        "label": label,
    }
    with connect(project_id) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO graph_snapshots(snapshot_id, project_id, label, snapshot_json, created_at) VALUES (?,?,?,?,?)",
            (snap_id, project_id, label, json.dumps(payload, ensure_ascii=False, default=str), _now()),
        )
    return snap_id


def list_snapshots(project_id: str) -> list[dict]:
    with connect(project_id) as conn:
        rows = conn.execute(
            "SELECT snapshot_id, label, created_at FROM graph_snapshots WHERE project_id=? ORDER BY created_at DESC",
            (project_id,),
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Public aliases used by the v2/v3 callers
# ---------------------------------------------------------------------------

def apply_diff(project_id: str) -> dict:
    return diff_and_apply(project_id)


def ensure_initialised(project_id: str) -> None:
    with connect(project_id) as conn:
        _ensure_tables(conn)


def _ensure_tables(conn: sqlite3.Connection) -> None:
    """Idempotent schema bootstrap (v1 + v2/v3 additions)."""
    conn.executescript(_SCHEMA_SQL)
    conn.execute(
        "INSERT OR REPLACE INTO schema_meta(key, value) VALUES('version', ?)",
        (str(SCHEMA_VERSION),),
    )


def get_nodes(project_id: str) -> list[dict]:
    return get_all_nodes(project_id)


def get_edges(project_id: str) -> list[dict]:
    return get_all_edges(project_id)


def get_communities(project_id: str) -> list[dict]:
    return load_communities(project_id)


def get_insights(project_id: str) -> list[dict]:
    return load_insights(project_id)


def execute(project_id: str, sql: str, params: tuple = ()) -> list[dict]:
    with connect(project_id) as conn:
        cur = conn.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]


def ensure_schema(project_id: str) -> None:
    with connect(project_id) as conn:
        conn.executescript(_SCHEMA_SQL)
        conn.execute(
            "INSERT OR REPLACE INTO schema_meta(key, value) VALUES('version', ?)",
            (str(SCHEMA_VERSION),),
        )


def record_event_alias(project_id: str, event_type: str, payload: dict) -> int:
    return record_event(project_id, event_type, payload)


def record_exposure(project_id: str, user_id: str, node_id: str) -> dict:
    fields = {
        "exposures": 1,
        "last_exposure_at": _now(),
    }
    return upsert_mastery(project_id, user_id, node_id, fields)


def record_attempt(
    project_id: str,
    user_id: str,
    node_id: str,
    score: float = 0.0,
    max_score: float = 1.0,
    *,
    correct: bool | None = None,
) -> dict:
    """v2/v3 compatible attempt recorder.

    ``score`` is normalised to [0, 1]; if ``correct`` is not supplied it is
    derived from the threshold the FSM uses (>= 0.5). All other state
    updates (BKT, SR, misconception) happen in the v3 observer layer.
    """
    pct = 0.0
    if max_score:
        pct = max(0.0, min(1.0, float(score) / float(max_score)))
    if correct is None:
        correct = pct >= 0.5
    level = "proficient" if correct else "learning"
    fields = {
        "level": level,
        "score": pct,
        "attempts": 1,
        "successes": 1 if correct else 0,
        "last_attempt_at": _now(),
    }
    return upsert_mastery(project_id, user_id, node_id, fields)


def record_graph_event(project_id, event_type, payload):
    return record_event(project_id, event_type, payload)
