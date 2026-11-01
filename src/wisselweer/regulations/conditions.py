"""Weercheck voor landen met een situationele plicht.

Pure functie over reeds opgehaalde verwachtingen. De detectie van vorst, sneeuw en gladheid is
dezelfde als die van de adviesengine (`core.engine.hour_flags`). Het resultaat beschrijft
*verwachte omstandigheden*; het is nooit een vaststelling dat een plicht geldt (de werkelijke
weg- en weersomstandigheid ter plaatse bepaalt dat).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from wisselweer.core import EngineConfig, Forecast
from wisselweer.core.engine import hour_flags
from wisselweer.regulations.models import ReferenceLocation

WINDOW_HOURS = 72
_HOUR = timedelta(hours=1)


class CountryCondition(StrEnum):
    WINTER_CONDITIONS_EXPECTED = "winter_conditions_expected"  # sneeuw of gladheid verwacht
    FROST_POSSIBLE = "frost_possible"  # alleen vorst
    NONE_EXPECTED = "none_expected"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class LocationFlags:
    name: str
    mountain: bool
    frost: bool
    snow: bool
    icy: bool


@dataclass(frozen=True)
class CountryConditions:
    status: CountryCondition
    partial: bool
    locations: list[LocationFlags]  # alleen locaties met bruikbare data
    window_hours: int = WINDOW_HOURS


def _usable(forecast: Forecast | None, now: datetime, cfg: EngineConfig) -> bool:
    if forecast is None:
        return False
    age_h = (now - forecast.fetched_at).total_seconds() / 3600
    if age_h > cfg.max_forecast_age_hours:
        return False
    end = now + timedelta(hours=WINDOW_HOURS)
    return any(p.temperature_c is not None and now - _HOUR < p.time < end for p in forecast.hourly)


def location_flags(
    ref: ReferenceLocation, forecast: Forecast, now: datetime, cfg: EngineConfig
) -> LocationFlags:
    """Vlaggen over de komende 72 uur voor één referentielocatie."""
    end = now + timedelta(hours=WINDOW_HOURS)
    frost = snow = icy = False
    for p in forecast.hourly:
        if not (now - _HOUR < p.time < end):
            continue
        f = hour_flags(p, cfg)
        frost, snow, icy = frost or f.frost, snow or f.snow, icy or f.icy
    return LocationFlags(ref.name, ref.mountain, frost, snow, icy)


def evaluate_country(
    items: list[tuple[ReferenceLocation, Forecast | None]],
    now: datetime,
    cfg: EngineConfig | None = None,
) -> CountryConditions:
    """Landelijke uitkomst uit de verwachtingen per referentielocatie.

    Ontbrekende of onbruikbare (te oude, lege) verwachtingen tellen niet mee; zijn er zowel
    bruikbare als onbruikbare locaties, dan is `partial` True. Zonder enige bruikbare data is
    de status UNKNOWN.
    """
    cfg = cfg or EngineConfig()
    flags = [
        location_flags(ref, fc, now, cfg)
        for ref, fc in items
        if fc is not None and _usable(fc, now, cfg)
    ]
    partial = 0 < len(flags) < len(items)
    if not flags:
        return CountryConditions(CountryCondition.UNKNOWN, partial=False, locations=[])
    if any(f.snow or f.icy for f in flags):
        status = CountryCondition.WINTER_CONDITIONS_EXPECTED
    elif any(f.frost for f in flags):
        status = CountryCondition.FROST_POSSIBLE
    else:
        status = CountryCondition.NONE_EXPECTED
    return CountryConditions(status, partial=partial, locations=flags)
