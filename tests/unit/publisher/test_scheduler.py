from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from tempfile import mkdtemp

from fastapi.testclient import TestClient

from wisselweer.api.app import create_app
from wisselweer.publisher import publish, scheduler
from wisselweer.settings import Settings


def _settings(**kw) -> Settings:
    return Settings(_env_file=None, data_dir=Path(mkdtemp()) / "data", **kw)


def test_default_is_off():
    s = _settings()
    assert s.publish_interval_hours == 0
    assert scheduler.start_scheduler(s) is None


def test_loop_runs_repeatedly_and_survives_errors(caplog):
    calls: list[int] = []

    def fn():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("geheim-pad /x/key")

    async def main():
        task = asyncio.create_task(scheduler.publish_loop(fn, 0.01, first_delay_s=0.01))
        for _ in range(200):
            if len(calls) >= 3:
                break
            await asyncio.sleep(0.01)
        await scheduler.stop_scheduler(task)
        assert task.cancelled() or task.done()

    with caplog.at_level(logging.ERROR, logger="wisselweer.publisher.scheduler"):
        asyncio.run(main())
    assert len(calls) >= 3
    assert "RuntimeError" in caplog.text
    assert "geheim-pad" not in caplog.text


def test_stop_none_is_noop():
    asyncio.run(scheduler.stop_scheduler(None))


def test_lifespan_starts_and_stops_task(monkeypatch):
    ran = []
    monkeypatch.setattr(scheduler, "FIRST_RUN_DELAY_S", 0.0)
    monkeypatch.setattr(publish, "run_publish", lambda s, *a: ran.append(1))
    monkeypatch.setattr(
        scheduler,
        "publish_loop",
        lambda fn, interval, first_delay_s=0.0: _orig(fn, 3600.0, 0.0),
    )
    s = _settings(publish_interval_hours=1)
    with TestClient(create_app(s)) as client:
        assert client.get("/api/v1/health").status_code == 200
        for _ in range(100):
            if ran:
                break
            import time

            time.sleep(0.02)
    assert ran


_orig = scheduler.publish_loop
