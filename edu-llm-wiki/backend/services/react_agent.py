"""ReAct agent for wiki Q&A, acting over an MCP tool server.

Classic ReAct (Yao et al., 2022) interleaves explicit reasoning with tool
actions instead of answering in one shot:

    Thought: I need the definition of X before I can compare it with Y.
    Action:  search_wiki(query="X 定义")
    Observation: 3 ranked matches, the second mentions Y's mechanism.
    Thought: Read the core page, then follow its graph edges.
    Action:  read_page(path="concepts/x.md")
    Observation: [1] X (...) ...content...
    Thought: I have enough evidence.
    Final Answer: ... [1] ...

Modern LLMs express the Action step natively as tool calls, so the loop runs
on function calling: each turn the model either requests tools (Thought +
Action) or emits the final answer. The Observation comes from MCP — the agent
holds a real ``ClientSession`` and discovers tools through ``tools/list``,
exactly as it would against a remote MCP server.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

from mcp import ClientSession

# mcp 1.x and 2.x ship different in-process transports with the same
# semantics: 2.x wraps the server in InMemoryTransport, 1.x offers a combined
# connected-session helper that also performs the initialize handshake.
try:  # mcp 2.x
    from mcp.client._memory import InMemoryTransport

    _MCP_TRANSPORT_V2 = True
except ImportError:  # mcp 1.x
    from mcp.shared.memory import create_connected_server_and_client_session

    _MCP_TRANSPORT_V2 = False

from services.llm_client import chat_complete, chat_complete_tools
from services.mcp_tools import EvidenceRegistry, build_wiki_tool_server


class ReactAgentError(Exception):
    """The ReAct loop failed; the caller should fall back to the legacy pipeline."""


@dataclass
class ReactResult:
    answer: str
    evidence: EvidenceRegistry
    steps: int = 0
    tool_calls: int = 0


REACT_SYSTEM_PROMPT = r"""You are a wiki tutor that retrieves evidence yourself before answering (the ReAct pattern: reason, act, observe, repeat until the evidence suffices, then answer).

## Interaction Mode
{mode_instruction}

## Output Language
{language_instruction}

## Tools
The MCP server provides wiki retrieval tools: search, read pages, follow graph edges, list the page directory, and read the learner's mastery state. Call a tool whenever the next piece of evidence would improve the answer; the tool result is the Observation for your next reasoning step. Batch independent tool calls in the same turn instead of sequencing them.

## Strategy
- Start with ``search_wiki`` unless the question names a specific page (then ``read_page`` directly) or asks about relationships/mechanisms (then read the core page and follow ``graph_neighbors``).
- Definition questions usually need one page. Comparison, mechanism, and multi-part questions need two to four pages, often reached through prerequisite / derives / applies_to edges.
- ``read_page`` observations begin with the page's citation number ``[n]``. Only pages you have read can be cited; reuse the exact ``[n]``.
- Stop calling tools as soon as the evidence covers the question — then answer.

## Learning-Plan Policy
When the learner asks about their learning plan or path ("规划学习路径", "我的学习路径", "把 X 提前", "调整路径"):
1. ALWAYS call ``get_learning_plan`` first. If it reports no plan exists, call ``rebuild_learning_plan``.
2. If a plan exists, read its snapshot comparison: rebuild ONLY when it shows material changes (new pages, new prerequisite edges, several mastery flips) or the learner explicitly asks to re-plan; otherwise summarise the stored plan as-is — do not rebuild unnecessarily.
3. Adjustment requests are executed with ``adjust_learning_plan``, one operation per user instruction (move_before / move_to_front / remove / annotate). Afterwards summarise the updated plan.
4. When presenting a plan, keep the level structure and per-topic status marks, and mention the current progress.

## Answer Rules
- Answer based on the pages you read. If they do not contain enough information, say so honestly.
- Use [[wikilink]] syntax to reference wiki pages.
- Cite with the ``[n]`` numbers from ``read_page``, e.g. [1], [2].
- Use LaTeX for mathematical formulas: inline $...$ and block $$...$$. Never write bare LaTeX commands like \sigma without $...$ delimiters.
- At the VERY END of your response, add a hidden comment listing which page numbers you used:
  <!-- cited: 1, 3 -->

## Learner Profile
{learner_profile}

## Current Assessment Context
{assessment_context}

## Wiki Purpose
{purpose}{scope_hint}"""


def _scope_hint(scope) -> str:
    if getattr(scope, "type", "") == "current_page" and getattr(scope, "page_path", None):
        return (
            f"\n\n## Current Page\nThe learner is reading `{scope.page_path}`; "
            "prioritise it when it is relevant to the question."
        )
    if getattr(scope, "type", "") == "selected_source" and getattr(scope, "source_name", None):
        return (
            f"\n\n## Selected Source\nThe learner selected source `{scope.source_name}`; "
            "prioritise its pages when they are relevant."
        )
    return ""


async def _emit(on_status, text: str, kind: str = "step") -> None:
    if on_status is None:
        return
    try:
        await on_status(text, kind)
    except TypeError:
        # Callers with the older single-argument signature still work.
        try:
            await on_status(text)
        except Exception:
            pass
    except Exception:
        # Status is best-effort; never fail the agent loop on a callback error.
        pass


def _observation_text(result) -> str:
    parts = [block.text for block in (result.content or []) if getattr(block, "text", None)]
    body = "\n".join(parts).strip()
    is_error = bool(getattr(result, "is_error", getattr(result, "isError", False)))
    if is_error:
        return f"ERROR: {body or 'tool call failed'}"
    return body or "(empty result)"


def _tool_definition(tool) -> dict:
    """Normalise a listed MCP tool across mcp 1.x/2.x attribute naming."""
    schema = getattr(tool, "input_schema", None) or getattr(tool, "inputSchema", None)
    return {
        "name": tool.name,
        "description": tool.description or "",
        "input_schema": schema or {"type": "object", "properties": {}},
    }


async def run_react_agent(
    query: str,
    messages: list[dict],
    *,
    project_id: str = "default",
    user_id: str = "default",
    budget: dict | None = None,
    mode_instruction: str = "",
    language_instruction: str = "",
    learner_profile: str = "No learner state available yet.",
    assessment_context: str = "(No recent assessment context.)",
    purpose: str = "Not defined",
    scope=None,
    model: str | None = None,
    max_steps: int = 8,
    on_status=None,
    abort_signal: asyncio.Event | None = None,
) -> ReactResult:
    """Run the ReAct loop until the model answers or the step budget runs out.

    Raises ``ReactAgentError`` when tool calling fails (unsupported model,
    provider outage); callers fall back to the legacy graph pipeline. Abort
    signals raise ``asyncio.CancelledError`` and are never converted.
    """
    budget = budget or {}
    evidence = EvidenceRegistry(page_budget=int(budget.get("page_budget", 20_000)))
    server = build_wiki_tool_server(
        project_id=project_id,
        user_id=user_id,
        evidence=evidence,
        max_page_size=int(budget.get("max_page_size", 5_000)),
    )
    system = REACT_SYSTEM_PROMPT.format(
        mode_instruction=mode_instruction or "Answer directly and concisely, with enough explanation to be useful.",
        language_instruction=language_instruction,
        learner_profile=learner_profile,
        assessment_context=assessment_context,
        purpose=purpose,
        scope_hint=_scope_hint(scope),
    )

    def _check_abort() -> None:
        if abort_signal is not None and abort_signal.is_set():
            raise asyncio.CancelledError("react agent aborted")

    async def _agent_loop(session: ClientSession) -> ReactResult:
        listed = await session.list_tools()
        tool_defs = [_tool_definition(tool) for tool in listed.tools]

        convo = [dict(message) for message in messages]
        tool_call_count = 0
        steps = 0
        for step in range(1, max_steps + 1):
            _check_abort()
            steps = step
            await _emit(on_status, f"ReAct 第 {step} 轮：规划下一步", "round")
            try:
                turn = await chat_complete_tools(
                    system,
                    convo,
                    tool_defs,
                    model=model,
                    temperature=0.2,
                    abort_signal=abort_signal,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                raise ReactAgentError(f"tool-calling turn failed: {exc}") from exc

            tool_calls = turn["tool_calls"]
            if not tool_calls:
                await _emit(on_status, "证据已足够，正在生成回答", "answer")
                return ReactResult(
                    answer=turn["content"],
                    evidence=evidence,
                    steps=steps,
                    tool_calls=tool_call_count,
                )

            # The model's inter-tool reasoning text is the visible chain of
            # thought for the UI; surface it before the actions it produced.
            thought = (turn["content"] or "").strip()
            if thought:
                await _emit(on_status, thought[:400], "thought")

            convo.append({
                "role": "assistant",
                "content": turn["content"],
                "tool_calls": tool_calls,
            })
            for call in tool_calls:
                _check_abort()
                tool_call_count += 1
                await _emit(
                    on_status,
                    f"调用工具 {call['name']}({json.dumps(call['arguments'], ensure_ascii=False)[:120]})",
                    "action",
                )
                pages_before = len(evidence.pages)
                try:
                    result = await session.call_tool(call["name"], dict(call["arguments"] or {}))
                    observation = _observation_text(result)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    observation = f"ERROR: {exc}"
                convo.append({
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": observation,
                })
                if len(evidence.pages) > pages_before:
                    page = evidence.pages[-1]
                    await _emit(on_status, f"已读取 [{page['number']}] {page['title']}", "step")

        # Step budget exhausted: force a final answer from the evidence
        # already read. The original message history carries no tool
        # turns, so plain chat_complete is safe for every provider.
        await _emit(on_status, "已达工具调用上限，基于已读页面作答", "answer")
        evidence_block = "\n\n".join(
            f"[{page['number']}] {page['title']} ({page['path']})\n\n{page['content']}"
            for page in evidence.pages
        ) or "(no pages were read)"
        final_system = (
            system
            + "\n\n## Final Turn\nThe tool-call budget is exhausted. Using ONLY the "
            "evidence below, answer the question now with the Answer Rules above.\n\n"
            f"## Evidence Read\n{evidence_block}"
        )
        try:
            answer = await chat_complete(
                system_prompt=final_system,
                messages=[dict(message) for message in messages],
                model=model,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise ReactAgentError(f"final answer generation failed: {exc}") from exc
        return ReactResult(answer=answer or "", evidence=evidence, steps=steps, tool_calls=tool_call_count)

    _check_abort()
    try:
        if _MCP_TRANSPORT_V2:
            async with (
                InMemoryTransport(server) as (read_stream, write_stream),
                ClientSession(read_stream, write_stream) as session,
            ):
                await session.initialize()
                return await _agent_loop(session)
        async with create_connected_server_and_client_session(server) as session:
            # The 1.x helper performs the initialize handshake internally.
            return await _agent_loop(session)
    except Exception as exc:
        # The 1.x transports wrap loop exceptions in anyio task groups, which
        # surfaces as an ExceptionGroup. Unwrap the first leaf so callers see
        # the original exception type (ReactAgentError stays recognisable for
        # the fallback decision). Groups holding BaseException members, e.g.
        # cancellation, do not match ``except Exception`` and propagate as-is.
        leaves = getattr(exc, "exceptions", None)
        if leaves:
            leaf = leaves[0]
            while getattr(leaf, "exceptions", None):
                leaf = leaf.exceptions[0]
            raise leaf from exc
        raise
