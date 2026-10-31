"""Diagnostische vergelijking van providers per dag.

Alleen ter diagnose: deze module combineert, middelt of kiest NIETS. De uitkomst mag
niet als invoer voor de adviesengine dienen.
"""

from __future__ import annotations

from datetime import date
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from wisselweer.core.models import Forecast


class ProviderDay(BaseModel):
    hours: int
    temp_min_c: float | None = None
    temp_max_c: float | None = None
    precip_mm: float | None = None


class DayComparison(BaseModel):
    day: date
    providers: dict[str, ProviderDay] = Field(default_factory=dict)
    temp_min_spread_c: float | None = None
    temp_max_spread_c: float | None = None
    precip_spread_mm: float | None = None


def _spread(values: list[float]) -> float | None:
    return round(max(values) - min(values), 3) if len(values) >= 2 else None


def compare_forecasts(forecasts: list[Forecast], tz: str | ZoneInfo) -> list[DayComparison]:
    zone = ZoneInfo(tz) if isinstance(tz, str) else tz
    days: dict[date, dict[str, ProviderDay]] = {}
    for fc in forecasts:
        buckets: dict[date, list] = {}
        for p in fc.hourly:
            buckets.setdefault(p.time.astimezone(zone).date(), []).append(p)
        for d, pts in buckets.items():
            temps = [p.temperature_c for p in pts if p.temperature_c is not None]
            precs = [p.precip_mm for p in pts if p.precip_mm is not None]
            days.setdefault(d, {})[fc.provider] = ProviderDay(
                hours=len(pts),
                temp_min_c=min(temps) if temps else None,
                temp_max_c=max(temps) if temps else None,
                precip_mm=round(sum(precs), 3) if precs else None,
            )
    out = []
    for d in sorted(days):
        pd = days[d]
        out.append(
            DayComparison(
                day=d,
                providers=pd,
                temp_min_spread_c=_spread(
                    [v.temp_min_c for v in pd.values() if v.temp_min_c is not None]
                ),
                temp_max_spread_c=_spread(
                    [v.temp_max_c for v in pd.values() if v.temp_max_c is not None]
                ),
                precip_spread_mm=_spread(
                    [v.precip_mm for v in pd.values() if v.precip_mm is not None]
                ),
            )
        )
    return out
