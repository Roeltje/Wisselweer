"""Bouwt uurlijkse Forecasts uit compacte dagprofielen (geen netwerk)."""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta
from typing import NamedTuple
from zoneinfo import ZoneInfo

from wisselweer.core import Forecast, HourlyPoint, PrecipType

AMS = ZoneInfo("Europe/Amsterdam")
ALL_VARS = {
    "temperature_c",
    "dew_point_c",
    "humidity_pct",
    "precip_mm",
    "precip_type",
    "snow_cm",
    "precip_probability_pct",
    "wind_speed_ms",
}


class Day(NamedTuple):
    """Eén dag: min/max temperatuur, neerslag (mm per dag) en type."""

    tmin: float
    tmax: float
    precip_mm: float = 0.0
    precip_type: PrecipType = PrecipType.NONE


def repeat(day: Day, n: int) -> list[Day]:
    return [day] * n


def make_forecast(
    start: date,
    days: list[Day],
    *,
    provider: str = "fixture",
    fetched_at: datetime | None = None,
    is_stale: bool = False,
    drop: tuple[str, ...] = (),
    dew_offset: float = 2.0,
    humidity: float = 70.0,
    tz: ZoneInfo = AMS,
) -> Forecast:
    """Uurlijkse forecast vanaf lokale middernacht van `start`.

    Temperatuur: cosinus met minimum om 03:00 en maximum om 15:00 lokale tijd.
    Neerslag wordt gelijk over de 24 uren verdeeld (sneeuw: 1 mm = 1 cm).
    """
    t0 = datetime(start.year, start.month, start.day, tzinfo=tz).astimezone(UTC)
    end = datetime.combine(start + timedelta(days=len(days)), datetime.min.time(), tzinfo=tz)
    points: list[HourlyPoint] = []
    t = t0
    while t < end.astimezone(UTC):
        local = t.astimezone(tz)
        idx = (local.date() - start).days
        d = days[idx]
        mean, amp = (d.tmin + d.tmax) / 2, (d.tmax - d.tmin) / 2
        hour = local.hour + local.minute / 60
        temp = mean + amp * math.cos(2 * math.pi * (hour - 15) / 24)
        raining = d.precip_mm > 0
        values = {
            "time": t,
            "temperature_c": round(temp, 2),
            "dew_point_c": round(temp - dew_offset, 2),
            "humidity_pct": humidity,
            "precip_mm": d.precip_mm / 24 if raining else 0.0,
            "precip_type": d.precip_type if raining else PrecipType.NONE,
            "snow_cm": (d.precip_mm / 24 if d.precip_type == PrecipType.SNOW else 0.0),
            "precip_probability_pct": 90.0 if raining else 5.0,
            "wind_speed_ms": 3.0,
        }
        for key in drop:
            values[key] = None
        points.append(HourlyPoint(**values))
        t += timedelta(hours=1)
    return Forecast(
        provider=provider,
        latitude=52.1,
        longitude=5.18,
        timezone=str(tz),
        fetched_at=fetched_at or t0,
        is_stale=is_stale,
        hourly=points,
        available_variables=ALL_VARS - set(drop),
    )
