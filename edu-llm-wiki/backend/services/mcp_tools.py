"""MCP tool server exposing the wiki's retrieval capabilities to the agent.

Each chat request builds one ``MCPServer`` whose tool handlers close over the
request context (project, learner, budget, citation registry). The ReAct agent
connects through an in-memory MCP client session, so the tool layer speaks the
same JSON-RPC protocol a real MCP client would use over stdio/HTTP — tool
discovery (``tools/list``) and invocation (``tools/call``) included — without
spawning a separate process.

Swapping this server for a remote one (stdio subprocess, Streamable HTTP)
would not change the agent: MCP keeps the tool contract on the protocol side.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field

# The runtime environments carry different mcp major versions: the backend
# process runs mcp 1.x (FastMCP) while fresh venvs resolve to 2.x (MCPServer).
# The tool-decorator surface used here is identical in both, so one import
# alias keeps this module loadable everywhere.
try:  # mcp 2.x
    from mcp.server.mcpserver import MCPServer as WikiMcpServer
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as WikiMcpServer

from services.graph_store import get_edges, get_nodes
from services.ingest_engine import _strip_images
from storage.wiki_store import is_private_learner_page_path, read_wiki_page

_MAX_PAGE_DIRECTORY = 120
_MAX_NEIGHBOURS = 12


def _compact(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", (text or "")).strip()
    return text if len(text) <= limit else text[: max(0, limit - 1)].rstrip() + "…"


@dataclass
class EvidenceRegistry:
    """Pages the agent actually read; these become the citable references.

    ``read_page`` assigns each page a stable ``[n]`` number that appears in the
    tool observation. The final answer must reuse that exact number, so the
    citation numbering the model sees is the numbering the response carries.
    """

    pages: list[dict] = field(default_factory=list)
    by_path: dict[str, dict] = field(default_factory=dict)
    page_budget: int = 20_000
    used_chars: int = 0

    def add(self, path: str, title: str, content: str) -> dict:
        if path in self.by_path:
            return self.by_path[path]
        number = len(self.pages) + 1
        page = {
            "number": number,
            "path": path,
            "title": title or path,
            "content": content,
            "snippet": _compact(content, 320),
        }
        self.pages.append(page)
        self.by_path[path] = page
        return page

    def remaining_chars(self) -> int:
        return max(0, self.page_budget - self.used_chars)

    def citation_list(self) -> str:
        return ", ".join(f"[{page['number']}] {page['title']}" for page in self.pages)


def _visible_summaries(project_id: str) -> list[dict]:
    # Import lazily: list_wiki_pages walks the project directory.
    from storage.wiki_store import list_wiki_pages

    return [
        summary for summary in list_wiki_pages(project_id=project_id)
        if summary.get("type") != "learner_profile"
        and not is_private_learner_page_path(str(summary.get("path") or ""))
    ]


def build_wiki_tool_server(
    *,
    project_id: str = "default",
    user_id: str = "default",
    evidence: EvidenceRegistry,
    max_page_size: int = 5_000,
    practice_cards: list | None = None,
) -> WikiMcpServer:
    """Build a per-request MCP server exposing wiki retrieval tools.

    ``practice_cards`` is an outbox: the ``issue_practice_questions`` tool
    appends the server-owned cards it issues so the chat route can stream
    them as structured card events instead of leaving the model to invent
    question text in markdown.
    """

    server = WikiMcpServer(name="edu-wiki-retrieval")

    @server.tool()
    async def search_wiki(query: str, top_k: int = 8) -> str:
        """Hybrid semantic + keyword search over public wiki pages.

        Returns ranked matches with path, title, and a short snippet. Start
        here to locate pages about the question, then read the best matches.
        """
        merged: dict[str, dict] = {}

        try:
            from services.vector_store import vector_search

            visible = {
                summary["path"] for summary in await asyncio.to_thread(
                    _visible_summaries, project_id
                )
            }
            hits = await asyncio.to_thread(vector_search, query, top_k=20, project_id=project_id)
            for index, hit in enumerate(hits):
                path = hit.get("path")
                if path not in visible:
                    continue
                merged[path] = {
                    "path": path,
                    "title": hit.get("title", ""),
                    "snippet": hit.get("snippet", ""),
                    "score": 15.0 - index * 0.5,
                }
        except Exception:
            pass

        try:
            from services.search_engine import keyword_search

            hits = await asyncio.to_thread(keyword_search, query, top_k=10, project_id=project_id)
            for hit in hits:
                existing = merged.get(hit.get("path"))
                if existing is not None:
                    existing["score"] += 2.0
                else:
                    merged[hit["path"]] = {
                        "path": hit["path"],
                        "title": hit.get("title", ""),
                        "snippet": hit.get("snippet", ""),
                        "score": max(1.0, float(hit.get("score", 0) or 0) * 0.7),
                    }
        except Exception:
            pass

        ranked = sorted(merged.values(), key=lambda r: -r["score"])[: max(1, top_k)]
        if not ranked:
            return "No wiki pages matched this query."
        lines = []
        for index, result in enumerate(ranked, 1):
            lines.append(
                f"{index}. {result['title']} ({result['path']}) — {_compact(result['snippet'], 160)}"
            )
        return "\n".join(lines)

    @server.tool()
    async def read_page(path: str, max_chars: int = 4000) -> str:
        """Read one wiki page's markdown content.

        The observation begins with the page's citation number in the form
        ``[n] Title (path)``. When the final answer cites this page, reuse that
        exact ``[n]``. Only pages you have read can be cited.
        """
        page = await asyncio.to_thread(read_wiki_page, path, project_id=project_id)
        if (
            page is None
            or page.get("page_type") == "learner_profile"
            or is_private_learner_page_path(path)
        ):
            return "Page not found or not readable."

        registered = evidence.by_path.get(path)
        if registered is not None:
            return (
                f"[{registered['number']}] {registered['title']} ({path}) "
                f"was already read; cite it as [{registered['number']}]."
            )

        content = _strip_images(page.get("content", "") or "")
        if not content.strip():
            return "This page has no readable content."

        remaining = evidence.remaining_chars()
        if remaining <= 0:
            return (
                "Context budget exhausted — stop reading and answer with the pages "
                f"already read: {evidence.citation_list()}."
            )
        limit = min(int(max_chars), max_page_size, remaining)
        body = content[:limit]
        if len(content) > limit:
            body += "\n\n[...truncated...]"
        evidence.used_chars += len(body)
        registered = evidence.add(path, page.get("title") or path, body)
        return f"[{registered['number']}] {registered['title']} ({path})\n\n{body}"

    @server.tool()
    async def graph_neighbors(path: str, edge_types: str = "") -> str:
        """List typed graph edges from one wiki page to its neighbours.

        Use this for prerequisites, mechanisms, derivations, and contrasts
        that keyword search misses. ``edge_types`` is an optional
        comma-separated filter, e.g. ``prerequisite,derives``.

        Each line shows the neighbour title, its path, the edge direction and
        type, and the edge evidence. Read a neighbour with ``read_page`` before
        citing it.
        """

        def collect() -> list[str]:
            wanted = {t.strip() for t in edge_types.split(",") if t.strip()}
            nodes = get_nodes(project_id)
            by_path = {}
            by_id = {}
            for node in nodes:
                node_path = str(node.get("page_path") or node.get("metadata", {}).get("path") or "")
                if node_path:
                    by_path[node_path] = node
                by_id[node.get("id")] = node
            node = by_path.get(path)
            if node is None:
                return []
            lines: list[str] = []
            for edge in get_edges(project_id):
                if wanted and edge.get("edge_type") not in wanted:
                    continue
                if float(edge.get("weight", 0) or 0) < 0.35:
                    continue
                if edge.get("source") == node.get("id"):
                    direction, other_id = "→", edge.get("target", "")
                elif edge.get("target") == node.get("id"):
                    direction, other_id = "←", edge.get("source", "")
                else:
                    continue
                other = by_id.get(other_id) or {}
                other_path = str(other.get("page_path") or other.get("metadata", {}).get("path") or "")
                if not other_path:
                    continue
                line = (
                    f"{direction} {edge.get('edge_type', 'related')} "
                    f"(w={float(edge.get('weight', 0) or 0):.2f}) "
                    f"{other.get('label') or other.get('title') or other_id} ({other_path})"
                )
                edge_evidence = edge.get("evidence") or edge.get("rationale") or ""
                if edge_evidence:
                    line += f" — {_compact(edge_evidence, 200)}"
                lines.append(line)
                if len(lines) >= _MAX_NEIGHBOURS:
                    break
            return lines

        lines = await asyncio.to_thread(collect)
        if not lines:
            return f"No usable graph edges found from {path}."
        return f"Graph neighbours of {path}:\n" + "\n".join(lines)

    @server.tool()
    async def list_wiki_pages() -> str:
        """List public wiki page titles and paths (the page directory)."""
        summaries = await asyncio.to_thread(_visible_summaries, project_id)
        lines = [
            f"- {summary.get('title')} ({summary.get('path')})"
            for summary in summaries[:_MAX_PAGE_DIRECTORY]
        ]
        if not lines:
            return "The wiki has no pages yet."
        extra = len(summaries) - len(lines)
        if extra > 0:
            lines.append(f"... and {extra} more")
        return "\n".join(lines)

    @server.tool()
    async def learner_state() -> str:
        """Read the learner's BKT mastery and SM-2 review state.

        Use it to pitch explanation depth and targeted feedback. Do not invent
        learner data beyond this summary.
        """
        try:
            from services.mastery import learner_state_summary

            state = await asyncio.to_thread(learner_state_summary, project_id, user_id)
        except Exception:
            return "No learner state available yet."
        weak = ", ".join(
            f"{item.get('title', item.get('kc_id'))} ({float(item.get('p_known', 0)):.2f})"
            for item in (state.get("weak_kcs") or [])[:5]
        ) or "none recorded"
        misconceptions = ", ".join(
            f"{item.get('label', item.get('tag'))} x{item.get('count', 0)}"
            for item in (state.get("misconception_clusters") or [])[:3]
        ) or "none recorded"
        return (
            f"- average mastery: {float(state.get('p_known_avg', 0) or 0):.2f}\n"
            f"- weak knowledge components: {weak}\n"
            f"- recurring misconception patterns: {misconceptions}\n"
            f"- due review items today: {int(state.get('sr_due_today', 0) or 0)}\n"
            f"- overconfidence gap: {float(state.get('overconfidence_gap', 0) or 0):.2f}\n"
            f"- prerequisite readiness: {float(state.get('readiness', 0) or 0):.2f}"
        )

    @server.tool()
    async def issue_practice_questions(
        topic: str = "",
        count: int = 1,
        difficulty: str = "mixed",
        question_type: str = "",
    ) -> str:
        """Issue server-owned practice question cards for the learner.

        Whenever the learner asks to be quizzed in ANY wording ("考考我",
        "考察一下我", "出题", "给我来几道题", "test me"), call this tool
        instead of writing question text yourself — the cards are graded,
        update BKT/SM-2, and render as answerable cards in the chat.

        ``count`` follows the learner's request (default 1, max 10); ``topic``
        is an optional subject; ``difficulty`` is easy/medium/hard/mixed.
        ``question_type`` is the card type the learner named, one of
        "multiple_choice" (选择题/单选), "short_answer" (简答/问答),
        "fill_blank" (填空), or "true_false" (判断题 — renders as a card with
        exactly two options, 正确/错误) — empty means the learner did not
        specify.
        After issuing, briefly tell the learner how many cards arrived and
        prompt them to answer; do not repeat or rewrite the questions.
        """
        try:
            from services.agent_assessment import create_question

            named_type = question_type.strip().lower()
            card_style = "true_false" if named_type == "true_false" else ""
            valid_types = {"multiple_choice", "short_answer", "fill_blank", "true_false"}
            question_types = (
                ["multiple_choice"] if card_style
                else ([named_type] if named_type in valid_types else None)
            )
            issued = []
            for _ in range(max(1, min(10, int(count)))):
                card = await create_question(
                    project_id,
                    user_id,
                    mode="practice",
                    session_id=None,
                    topic=(topic or "").strip() or None,
                    difficulty=difficulty,
                    question_types=question_types,
                    card_style=card_style,
                )
                if card.get("question") is None:
                    break
                issued.append(card)
        except Exception as exc:
            return f"ERROR issuing practice questions: {exc}"
        if not issued:
            return "No cards could be issued (knowledge base empty). Tell the learner to import material first."
        if practice_cards is not None:
            practice_cards.extend(issued)
        return (
            f"Issued {len(issued)} practice card(s). They will appear to the "
            "learner as answerable cards. Tell the learner the cards are ready "
            "and that they should answer; do NOT restate the questions yourself."
        )

    @server.tool()
    async def get_learning_plan() -> str:
        """Read the learner's persisted learning plan with a change diff.

        Returns the stored plan plus a deterministic comparison against the
        current graph and mastery state (new pages, new prerequisite edges,
        mastery flips). Decide from that diff whether the plan needs a
        rebuild: significant changes justify ``rebuild_learning_plan``;
        otherwise summarise the stored plan without rebuilding.
        """
        try:
            from services.learning.plan_store import plan_diff, read_plan

            plan = await asyncio.to_thread(read_plan, project_id, user_id)
            if plan is None:
                return (
                    "No learning plan exists for this learner yet. Call "
                    "rebuild_learning_plan to create one from the prerequisite graph."
                )
            diff = await asyncio.to_thread(plan_diff, project_id, user_id)
            markdown = plan["markdown"]
            if len(markdown) > 6000:
                markdown = markdown[:6000] + "\n[...truncated...]"
            return (
                f"## Stored plan (file: {plan['path']})\n\n{markdown}\n\n"
                "## Snapshot comparison (stored plan vs current state)\n"
                f"{json.dumps(diff, ensure_ascii=False, indent=2)}\n\n"
                "Use the comparison to decide: rebuild only when the summary shows "
                "material changes (new pages, new prerequisite edges, several mastery "
                "flips) or the learner explicitly asks to re-plan."
            )
        except Exception as exc:
            return f"ERROR reading learning plan: {exc}"

    @server.tool()
    async def rebuild_learning_plan(reason: str = "") -> str:
        """Rebuild the learning plan from all prerequisite graph edges.

        Integrates every knowledge node with its prerequisite relations into
        topological levels (level 1 = no prerequisites; same level = can be
        learned in parallel), overlays BKT mastery status, persists it as the
        learner's plan file, and returns the rendered plan. This resets any
        previous manual adjustments.
        """
        try:
            from services.learning.plan_store import write_plan

            result = await asyncio.to_thread(
                write_plan,
                project_id,
                user_id,
                reason=reason.strip() or "用户请求(重新)规划学习路径",
                overlay=[],
            )
            markdown = result["markdown"]
            if len(markdown) > 6000:
                markdown = markdown[:6000] + "\n[...truncated...]"
            return f"(plan persisted to {result['path']})\n\n{markdown}"
        except Exception as exc:
            return f"ERROR rebuilding learning plan: {exc}"

    @server.tool()
    async def adjust_learning_plan(operations: str, note: str = "") -> str:
        """Apply the learner's adjustments to the persisted learning plan.

        ``operations`` is a JSON array; each element is one operation:
        - {"op": "move_before", "node": "<label>", "before": "<label>"} — move
          a topic to the level of another topic (rejected if that would
          violate a prerequisite; both labels must be unambiguous).
        - {"op": "move_to_front", "node": "<label>"} — move to level 1.
        - {"op": "remove", "node": "<label>", "note": "why"} — drop topics. By
          default an exact label match removes only that node; when the learner
          asks to skip a whole area ("XX 的内容先不学", "液晶那些先不学"), add
          "cluster": true so every label containing the word is removed.
        - {"op": "annotate", "node": "<label>", "note": "text"} — attach a note.
        ``note`` on the call records the learner's original request for the
        audit trail. The result marks each operation as applied, skipped, or
        rejected — report failures to the learner honestly, never claim an
        adjustment succeeded when it did not.
        """
        try:
            from services.learning.plan_store import apply_adjustments

            try:
                parsed = json.loads(operations or "[]")
            except json.JSONDecodeError as exc:
                return f"ERROR: operations must be a JSON array ({exc})"
            if not isinstance(parsed, list) or not parsed:
                return "ERROR: operations must be a non-empty JSON array."
            result = await asyncio.to_thread(
                apply_adjustments, project_id, user_id, parsed, note.strip()
            )
            if result.get("error"):
                return f"ERROR: {result['error']}"
            report = result["report"]
            outcome_lines = [f"- ✅ 已生效: {item}" for item in report.get("applied") or []]
            outcome_lines += [f"- ⚠️ 未生效(跳过): {item}" for item in report.get("skipped") or []]
            outcome_lines += [f"- ⚠️ 被拒绝: {item}" for item in report.get("rejected") or []]
            outcome = "## Adjustment result\n" + "\n".join(outcome_lines) + "\n"
            if report.get("skipped") or report.get("rejected"):
                outcome += (
                    "\nIMPORTANT: the ⚠️ entries above did NOT take effect. You must "
                    "tell the user honestly which operations failed and why.\n"
                )
            markdown = result["markdown"]
            if len(markdown) > 6000:
                markdown = markdown[:6000] + "\n[...truncated...]"
            return (
                f"{outcome}\n"
                f"## Updated plan (persisted to {result['path']})\n\n{markdown}"
            )
        except Exception as exc:
            return f"ERROR adjusting learning plan: {exc}"

    return server
