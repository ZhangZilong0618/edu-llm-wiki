"""Startup lifecycle tests."""

import asyncio
import threading


def test_startup_does_not_wait_for_vector_index_build(monkeypatch):
    """A slow initial index build must not delay HTTP readiness."""
    import main

    started = threading.Event()
    release = threading.Event()

    def slow_index_build():
        started.set()
        release.wait(timeout=2)

    monkeypatch.setattr(main, "_migrate_to_projects", lambda: None)
    monkeypatch.setattr(main, "_materialize_project_wikis", lambda: None)
    monkeypatch.setattr(main, "_ensure_vector_indices", slow_index_build)

    async def run_startup():
        try:
            await asyncio.wait_for(main.startup(), timeout=0.2)
            task = main.app.state.vector_index_task
            assert not task.done()
            assert await asyncio.to_thread(started.wait, 1)
        finally:
            release.set()
            task = getattr(main.app.state, "vector_index_task", None)
            if task is not None:
                await asyncio.wait_for(task, timeout=2)

    asyncio.run(run_startup())
