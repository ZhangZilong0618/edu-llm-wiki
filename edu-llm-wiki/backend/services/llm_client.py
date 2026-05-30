import json
from typing import AsyncIterator
from openai import AsyncOpenAI
from anthropic import AsyncAnthropic
from config import settings


def get_llm_client():
    """Return the appropriate LLM client based on provider config."""
    provider = settings.llm_provider

    if provider == "anthropic":
        base_url = settings.llm_base_url or None
        return AsyncAnthropic(api_key=settings.llm_api_key, base_url=base_url)

    # OpenAI, Ollama, Custom (all OpenAI-compatible)
    base_url = settings.llm_base_url or None
    api_key = settings.llm_api_key or "ollama"  # ollama doesn't need a real key
    return AsyncOpenAI(api_key=api_key, base_url=base_url)


async def stream_chat(
    system_prompt: str,
    messages: list[dict],
    model: str | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
) -> AsyncIterator[str]:
    """Stream chat completion. Yields content chunks."""
    provider = settings.llm_provider
    model = model or settings.llm_model
    max_tokens = max_tokens or settings.llm_max_tokens
    temperature = temperature or settings.llm_temperature

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
            delta = chunk.choices[0].delta
            if delta.content:
                yield delta.content


async def chat_complete(
    system_prompt: str,
    messages: list[dict],
    model: str | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
    response_format: dict | None = None,
) -> str:
    """Non-streaming chat completion. Returns full response."""
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
        resp = await client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=anthropic_messages,
            temperature=temperature,
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

    resp = await client.chat.completions.create(**kwargs)
    return resp.choices[0].message.content


async def test_connection(data) -> tuple[bool, str]:
    """Test LLM connection with a minimal request. Returns (ok, message)."""
    provider = data.llm_provider
    base_url = data.llm_base_url or None
    api_key = data.llm_api_key or "ollama"
    model = data.llm_model
    max_tokens = data.llm_max_tokens
    temperature = data.llm_temperature

    try:
        if provider == "anthropic":
            client = AsyncAnthropic(api_key=api_key, base_url=base_url)
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
            client = AsyncOpenAI(api_key=api_key, base_url=base_url)
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
        # Extract useful info from common errors
        if "401" in msg or "Unauthorized" in msg:
            return False, "Authentication failed — check your API key"
        if "404" in msg or "Not Found" in msg:
            return False, f"Model '{model}' not found — check model name"
        if "Connection" in msg or "refused" in msg or "timeout" in msg:
            return False, f"Connection failed — check Base URL: {msg[:120]}"
        return False, msg[:200]
