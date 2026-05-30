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
