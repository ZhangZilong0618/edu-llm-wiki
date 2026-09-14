"""Test that stream_chat aborts cleanly when abort_signal is set."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from services import llm_client


def test_stream_chat_aborts_when_signal_set():
    """If the caller sets abort_signal up front, the generator must
    raise CancelledError so the underlying HTTP request is torn down."""
    chunks = ["hello", " world", " this", " should", " be", " aborted"]

    class _FakeDelta:
        def __init__(self, content):
            self.content = content

    class _FakeChoice:
        def __init__(self, content):
            self.delta = _FakeDelta(content)

    class _FakeChunk:
        def __init__(self, content):
            self.choices = [_FakeChoice(content)]

    async def _aiter(items):
        for item in items:
            yield item

    class _FakeStream:
        def __init__(self, items):
            self._items = _aiter(items)

        def __aiter__(self):
            return self

        async def __anext__(self):
            return await self._items.__anext__()

    async def run():
        with patch("services.llm_client.get_llm_client") as mock_get_client:
            client = AsyncMock()
            client.chat.completions.create = AsyncMock(
                side_effect=lambda *a, **kw: _FakeStream([_FakeChunk(c) for c in chunks])
            )
            mock_get_client.return_value = client

            abort = asyncio.Event()
            abort.set()  # set up front so the loop bails on the first poll

            produced = []
            with pytest.raises(asyncio.CancelledError):
                async for chunk in llm_client.stream_chat(
                    system_prompt="x",
                    messages=[{"role": "user", "content": "y"}],
                    abort_signal=abort,
                ):
                    produced.append(chunk)
            assert produced == []

    asyncio.run(run())


def test_stream_chat_yields_when_signal_not_set():
    """Without an abort signal, stream_chat yields all chunks normally."""
    class _FakeDelta:
        def __init__(self, content):
            self.content = content

    class _FakeChoice:
        def __init__(self, content):
            self.delta = _FakeDelta(content)

    class _FakeChunk:
        def __init__(self, content):
            self.choices = [_FakeChoice(content)]

    async def _aiter(items):
        for item in items:
            yield item

    class _FakeStream:
        def __init__(self, items):
            self._items = _aiter(items)

        def __aiter__(self):
            return self

        async def __anext__(self):
            return await self._items.__anext__()

    async def run():
        with patch("services.llm_client.get_llm_client") as mock_get_client:
            client = AsyncMock()
            chunks = ["a", "b", "c"]
            client.chat.completions.create = AsyncMock(
                side_effect=lambda *a, **kw: _FakeStream([_FakeChunk(c) for c in chunks])
            )
            mock_get_client.return_value = client

            abort = asyncio.Event()  # never set

            produced = []
            async for chunk in llm_client.stream_chat(
                system_prompt="x",
                messages=[{"role": "user", "content": "y"}],
                abort_signal=abort,
            ):
                produced.append(chunk)
            assert produced == chunks

    asyncio.run(run())
