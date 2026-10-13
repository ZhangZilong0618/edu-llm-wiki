import asyncio
import json
from collections.abc import AsyncIterator

import httpx

from config import settings

# Shared HTTP client that ignores system proxy settings.
# The system ALL_PROXY=socks://... breaks httpx (no SOCKS support).
_http_client = httpx.AsyncClient(trust_env=False, timeout=httpx.Timeout(180.0, connect=10.0))


def _client_for(provider: str, api_key: str, base_url: str | None):
    if provider == "anthropic":
        from anthropic import AsyncAnthropic
        return AsyncAnthropic(api_key=api_key, base_url=base_url, http_client=_http_client)
    from openai import AsyncOpenAI
    return AsyncOpenAI(api_key=api_key, base_url=base_url, http_client=_http_client)


def get_llm_client():
    """Return the appropriate LLM client based on provider config."""
    provider = settings.llm_provider
    api_key = settings.llm_api_key or "ollama"
    base_url = settings.llm_base_url or None
    return _client_for(provider, api_key, base_url)


async def stream_chat(
    system_prompt: str,
    messages: list[dict],
    model: str | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
    abort_signal: "asyncio.Event | None" = None,
) -> AsyncIterator[str]:
    """Stream chat completion. Yields content chunks.

    If ``abort_signal`` is provided, the caller can set it to stop iteration
    early. We poll the signal between chunks and raise ``CancelledError`` so
    the async generator is closed promptly and the underlying HTTP request
    is torn down. This avoids wasting tokens on responses the client has
    already discarded (e.g. when the user clicks Stop mid-stream).
    """
    provider = settings.llm_provider
    model = model or settings.llm_model
    max_tokens = max_tokens or settings.llm_max_tokens
    temperature = temperature or settings.llm_temperature

    async def _check_abort() -> None:
        if abort_signal is not None and abort_signal.is_set():
            raise asyncio.CancelledError("stream_chat aborted by caller")

    if provider == "anthropic":
        client = get_llm_client()
        # Convert to Anthropic format
        system = system_prompt
        anthropic_messages = [
            {"role": m["role"], "content": m["content"]} for m in messages
        ]
        async with client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=anthropic_messages,
            temperature=temperature,
        ) as stream:
            async for text in stream.text_stream:
                await _check_abort()
                yield text
    else:
        client = get_llm_client()
        # OpenAI-compatible
        full_messages = [{"role": "system", "content": system_prompt}] + messages
        stream = await client.chat.completions.create(
            model=model,
            messages=full_messages,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=True,
        )
        async for chunk in stream:
            await _check_abort()
            # OpenAI-compatible gateways commonly emit a final usage-only chunk
            # with an empty ``choices`` array. It is not a content delta and must
            # be skipped rather than raising IndexError.
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.content:
                yield delta.content


async def _await_with_abort(awaitable, abort_signal: "asyncio.Event | None"):
    """Await a request while allowing an Event to cancel it promptly."""
    if abort_signal is None:
        return await awaitable

    if abort_signal.is_set():
        awaitable.close()
        raise asyncio.CancelledError("chat_complete aborted by caller")

    request_task = asyncio.ensure_future(awaitable)
    abort_task = asyncio.ensure_future(abort_signal.wait())
    try:
        done, _pending = await asyncio.wait(
            {request_task, abort_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if request_task in done:
            return request_task.result()
        request_task.cancel()
        await asyncio.wait({request_task})
        raise asyncio.CancelledError("chat_complete aborted by caller")
    finally:
        abort_task.cancel()
        await asyncio.wait({abort_task})


async def chat_complete(
    system_prompt: str,
    messages: list[dict],
    model: str | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
    response_format: dict | None = None,
    abort_signal: "asyncio.Event | None" = None,
) -> str:
    """Non-streaming chat completion. Returns full response.

    ``abort_signal`` mirrors ``stream_chat``: setting it cancels the in-flight
    request so long-running controller calls do not continue after the caller
    disconnects.
    """
    provider = settings.llm_provider
    model = model or settings.llm_model
    max_tokens = max_tokens or settings.llm_max_tokens
    temperature = temperature or settings.llm_temperature

    if provider == "anthropic":
        client = get_llm_client()
        system = system_prompt
        anthropic_messages = [
            {"role": m["role"], "content": m["content"]} for m in messages
        ]
        resp = await _await_with_abort(
            client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=anthropic_messages,
                temperature=temperature,
            ),
            abort_signal,
        )
        return resp.content[0].text

    client = get_llm_client()
    full_messages = [{"role": "system", "content": system_prompt}] + messages
    kwargs = dict(
        model=model,
        messages=full_messages,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    if response_format:
        kwargs["response_format"] = response_format

    resp = await _await_with_abort(
        client.chat.completions.create(**kwargs),
        abort_signal,
    )
    if not resp.choices:
        return ""
    return resp.choices[0].message.content or ""


def _openai_tools(mcp_tools: list[dict]) -> list[dict]:
    """Convert MCP tool definitions to the OpenAI function-calling shape."""
    return [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description") or "",
                "parameters": tool.get("input_schema") or {"type": "object", "properties": {}},
            },
        }
        for tool in mcp_tools
    ]


def _anthropic_tools(mcp_tools: list[dict]) -> list[dict]:
    """Convert MCP tool definitions to the Anthropic tool shape."""
    return [
        {
            "name": tool["name"],
            "description": tool.get("description") or "",
            "input_schema": tool.get("input_schema") or {"type": "object", "properties": {}},
        }
        for tool in mcp_tools
    ]


def _openai_tool_message(message: dict) -> dict:
    """Serialise one internal message for the OpenAI wire format.

    Internal assistant turns carry ``tool_calls`` with ``arguments`` as a
    dict for easy manipulation; the OpenAI API wants them as a JSON string.
    """
    tool_calls = message.get("tool_calls")
    if not tool_calls:
        return message
    return {
        "role": "assistant",
        "content": message.get("content") or None,
        "tool_calls": [
            {
                "id": call["id"],
                "type": "function",
                "function": {
                    "name": call["name"],
                    "arguments": json.dumps(call.get("arguments") or {}, ensure_ascii=False),
                },
            }
            for call in tool_calls
        ],
    }


def _anthropic_messages(messages: list[dict]) -> list[dict]:
    """Convert internal (OpenAI-style) messages to Anthropic content blocks.

    Tool results must arrive inside a user turn right after the assistant
    turn that requested them, so consecutive tool messages are merged into a
    single user message of ``tool_result`` blocks.
    """
    out: list[dict] = []
    for message in messages:
        role = message["role"]
        if role == "tool":
            block = {
                "type": "tool_result",
                "tool_use_id": message.get("tool_call_id", ""),
                "content": message.get("content", ""),
            }
            if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                out[-1]["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
        elif role == "assistant" and message.get("tool_calls"):
            blocks = []
            text = (message.get("content") or "").strip()
            if text:
                blocks.append({"type": "text", "text": text})
            for call in message["tool_calls"]:
                blocks.append({
                    "type": "tool_use",
                    "id": call["id"],
                    "name": call["name"],
                    "input": call.get("arguments") or {},
                })
            out.append({"role": "assistant", "content": blocks})
        else:
            out.append({"role": role, "content": message.get("content", "")})
    return out


async def chat_complete_tools(
    system_prompt: str,
    messages: list[dict],
    tools: list[dict],
    *,
    model: str | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
    tool_choice: str = "auto",
    abort_signal: "asyncio.Event | None" = None,
) -> dict:
    """One LLM turn with tool calling over MCP-style tool definitions.

    ``tools`` uses the MCP tool shape ({name, description, input_schema}).
    ``messages`` uses the OpenAI shape, including assistant turns with
    ``tool_calls`` [{id, name, arguments(dict)}] and tool results
    ({role: "tool", tool_call_id, content}).

    Returns {"content": str, "tool_calls": [...], "stop_reason": "tool_calls"
    or "stop"} so the ReAct loop can treat both providers uniformly.
    """
    provider = settings.llm_provider
    model = model or settings.llm_model
    max_tokens = max_tokens or settings.llm_max_tokens
    temperature = temperature if temperature is not None else settings.llm_temperature

    if provider == "anthropic":
        client = get_llm_client()
        resp = await _await_with_abort(
            client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=_anthropic_messages(messages),
                tools=_anthropic_tools(tools),
                temperature=temperature,
            ),
            abort_signal,
        )
        text = "\n".join(
            block.text for block in resp.content if getattr(block, "type", "") == "text"
        ).strip()
        tool_calls = [
            {"id": block.id, "name": block.name, "arguments": dict(block.input or {})}
            for block in resp.content if getattr(block, "type", "") == "tool_use"
        ]
        return {
            "content": text,
            "tool_calls": tool_calls,
            "stop_reason": "tool_calls" if resp.stop_reason == "tool_use" else "stop",
        }

    client = get_llm_client()
    full_messages = [{"role": "system", "content": system_prompt}] + [
        _openai_tool_message(message) for message in messages
    ]
    kwargs = dict(
        model=model,
        messages=full_messages,
        max_tokens=max_tokens,
        temperature=temperature,
        tools=_openai_tools(tools),
    )
    if tool_choice != "auto":
        kwargs["tool_choice"] = tool_choice
    resp = await _await_with_abort(client.chat.completions.create(**kwargs), abort_signal)
    if not resp.choices:
        return {"content": "", "tool_calls": [], "stop_reason": "stop"}
    msg = resp.choices[0].message
    tool_calls = []
    for index, call in enumerate(msg.tool_calls or []):
        raw_arguments = call.function.arguments
        if isinstance(raw_arguments, str):
            try:
                arguments = json.loads(raw_arguments or "{}")
            except json.JSONDecodeError:
                arguments = {}
        else:
            arguments = dict(raw_arguments or {})
        tool_calls.append({
            # Some OpenAI-compatible gateways omit the call id; synthesise one
            # so the tool result can still be matched to the request.
            "id": call.id or f"call_{index}",
            "name": call.function.name,
            "arguments": arguments if isinstance(arguments, dict) else {},
        })
    return {
        "content": msg.content or "",
        "tool_calls": tool_calls,
        "stop_reason": "tool_calls" if tool_calls else "stop",
    }


async def test_connection(data) -> tuple[bool, str]:
    """Test LLM connection with a minimal request. Returns (ok, message)."""
    provider = data.llm_provider
    base_url = data.llm_base_url or None
    api_key = data.llm_api_key or "ollama"
    model = data.llm_model
    max_tokens = data.llm_max_tokens
    temperature = data.llm_temperature

    try:
        client = _client_for(provider, api_key, base_url)
        if provider == "anthropic":
            resp = await client.messages.create(
                model=model,
                max_tokens=min(max_tokens, 50),
                system="Reply with exactly: OK",
                messages=[{"role": "user", "content": "Say OK"}],
                temperature=temperature,
            )
            content = resp.content[0].text if resp.content else ""
            return True, f"Connected — model responded: {content[:80]}"
        else:
            resp = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "Reply with exactly: OK"},
                    {"role": "user", "content": "Say OK"},
                ],
                max_tokens=min(max_tokens, 50),
                temperature=temperature,
            )
            content = resp.choices[0].message.content or ""
            return True, f"Connected — model responded: {content[:80]}"
    except Exception as e:
        msg = str(e)
        if "401" in msg or "Unauthorized" in msg:
            return False, "Authentication failed — check your API key"
        if "404" in msg or "Not Found" in msg:
            return False, f"Model '{model}' not found — check model name"
        if "Connection" in msg or "refused" in msg or "timeout" in msg:
            return False, f"Connection failed — check Base URL: {msg[:120]}"
        return False, msg[:200]
