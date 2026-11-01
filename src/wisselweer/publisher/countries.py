"""Landenregels voor `advice.json` (optioneel veld `countries`).

Haalt verwachtingen op voor de referentielocaties van landen met een situationele plicht, via
dezelfde `ForecastService` (cache, If-Modified-Since, stale-fallback) als het landelijke advies.
Sequentieel; elke locatie wordt per publicatie hooguit één keer opgevraagd. Een providerfout
maakt van die locatie een gat (`partial`), nooit een fout in de publicatie.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from wisselweer.core import EngineConfig, Forecast
from wisselweer.publisher.public_schema import (
    PublicCountry,
    PublicCountryLink,
    PublicCountryLocation,
    PublicCountryWeather,
)
from wisselweer.regulations.conditions import CountryConditions, evaluate_country
from wisselweer.regulations.loader import load_country_rules, load_disclaimer
from wisselweer.regulations.models import CountryRule
from wisselweer.regulations.period import in_period, period_label_nl

if TYPE_CHECKING:
    from wisselweer.weather.service import ForecastService

log = logging.getLogger("wisselweer.publisher")


def _weather(conditions: CountryConditions) -> PublicCountryWeather:
    return PublicCountryWeather(
        status=conditions.status.value,  # type: ignore[arg-type]
        partial=conditions.partial,
        locations=[
            PublicCountryLocation(
                name=f.name, mountain=f.mountain, frost=f.frost, snow=f.snow, icy=f.icy
            )
            for f in conditions.locations
        ],
        window_hours=conditions.window_hours,
    )


def build_public_country(
    rule: CountryRule, conditions: CountryConditions | None, today
) -> PublicCountry:
    return PublicCountry(
        code=rule.code,
        name=rule.name_nl,
        rule_types=[rt.value for rt in rule.rule_types],  # type: ignore[misc]
        period_label=period_label_nl(rule.period) if rule.period else None,
        in_period=in_period(rule.period, today) if rule.period else None,
        conditions_text=rule.conditions_nl,
        tires_text=rule.tires_nl,
        min_tread_mm=rule.min_tread_mm,
        alternatives_text=rule.alternatives_nl,
        notes_text=rule.notes_nl,
        sources=[PublicCountryLink(title=s.title, url=s.url) for s in rule.sources],
        checked_on=rule.checked_on,
        confidence=rule.confidence,
        weather=_weather(conditions) if conditions is not None else None,
    )


def build_public_countries(
    forecasts: ForecastService,
    now: datetime | None = None,
    *,
    rules: list[CountryRule] | None = None,
    cfg: EngineConfig | None = None,
    today=None,
) -> tuple[list[PublicCountry], str]:
    """Bouwt de publieke landenlijst en de disclaimer."""
    from zoneinfo import ZoneInfo

    now = (now or datetime.now(UTC)).astimezone(UTC)
    today = today or now.astimezone(ZoneInfo("Europe/Amsterdam")).date()
    rules = rules if rules is not None else load_country_rules()
    cache: dict[tuple[float, float], Forecast | None] = {}

    def fetch(lat: float, lon: float) -> Forecast | None:
        key = (round(lat, 4), round(lon, 4))
        if key not in cache:
            try:
                cache[key] = forecasts.get_forecast(*key)
            except Exception as exc:  # noqa: BLE001 - elke providerfout ⇒ locatie zonder data
                log.warning("country_forecast_failed type=%s", type(exc).__name__)
                cache[key] = None
        return cache[key]

    countries: list[PublicCountry] = []
    for rule in rules:
        conditions = None
        if rule.is_situational:
            items = [(loc, fetch(loc.latitude, loc.longitude)) for loc in rule.reference_locations]
            conditions = evaluate_country(items, now, cfg)
        countries.append(build_public_country(rule, conditions, today))
    return countries, load_disclaimer()
