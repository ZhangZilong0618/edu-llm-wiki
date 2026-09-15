from collections.abc import AsyncIterator

import asyncio
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
