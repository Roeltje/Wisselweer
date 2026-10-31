"""Optionele interne publicatieplanner (alternatief voor een systemd-timer of cron)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from wisselweer.settings import Settings

log = logging.getLogger("wisselweer.publisher.scheduler")

FIRST_RUN_DELAY_S = 60.0


async def publish_loop(
    publish_fn: Callable[[], Any],
    interval_s: float,
    first_delay_s: float = FIRST_RUN_DELAY_S,
) -> None:
    """Draait `publish_fn` in een thread: eerst na `first_delay_s`, daarna elke `interval_s`.

    Fouten worden alleen als type gelogd (geen traceback: kan paden of secrets bevatten) en
    stoppen de lus niet. Annuleren (shutdown) beëindigt de lus netjes.
    """
    await asyncio.sleep(first_delay_s)
    while True:
        try:
            await asyncio.to_thread(publish_fn)
            log.info("scheduled_publish_ok")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error("scheduled_publish_failed type=%s", type(exc).__name__)
        await asyncio.sleep(interval_s)


def start_scheduler(settings: Settings) -> asyncio.Task[None] | None:
    """Start de taak als `publish_interval_hours > 0`; anders `None`."""
    if settings.publish_interval_hours <= 0:
        return None
    from wisselweer.publisher.publish import run_publish

    log.info("publish_scheduler_enabled interval_hours=%s", settings.publish_interval_hours)
    return asyncio.create_task(
        publish_loop(lambda: run_publish(settings), settings.publish_interval_hours * 3600.0),
        name="wisselweer-publish-scheduler",
    )


async def stop_scheduler(task: asyncio.Task[None] | None) -> None:
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
