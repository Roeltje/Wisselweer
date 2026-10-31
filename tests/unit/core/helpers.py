from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from tests.fixtures.builders import Day, make_forecast, repeat
from wisselweer.core import (
    Advice,
    AdviceInput,
    DrivingProfile,
    EngineConfig,
    Forecast,
    TireType,
    evaluate,
)

# Maandag 2 nov 2026, 08:00 lokaal (CET = UTC+1)
AUTUMN_START = date(2026, 11, 2)
AUTUMN_NOW = datetime(2026, 11, 2, 7, 0, tzinfo=UTC)

__all__ = ["AUTUMN_NOW", "AUTUMN_START", "Day", "repeat", "run", "forecast"]


def forecast(
    days: list[Day], start: date = AUTUMN_START, now: datetime = AUTUMN_NOW, **kw
) -> Forecast:
    kw.setdefault("fetched_at", now - timedelta(hours=1))
    return make_forecast(start, days, **kw)


def run(
    days: list[Day] | None,
    mounted: TireType | None = TireType.SUMMER,
    *,
    start: date = AUTUMN_START,
    now: datetime = AUTUMN_NOW,
    profile: DrivingProfile | None = None,
    lead_time_days: int = 7,
    previous: Advice | None = None,
    config: EngineConfig | None = None,
    fc: Forecast | None = None,
    **fc_kw,
) -> Advice:
    if fc is None and days is not None:
        fc = forecast(days, start, now, **fc_kw)
    return evaluate(
        AdviceInput(
            forecast=fc,
            mounted=mounted,
            profile=profile or DrivingProfile.commute(),
            now=now,
            previous=previous,
            lead_time_days=lead_time_days,
            config=config or EngineConfig(),
        )
    )
