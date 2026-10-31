from __future__ import annotations

from datetime import UTC, date, datetime

from tests.fixtures.builders import Day, make_forecast, repeat
from wisselweer.core import Forecast
from wisselweer.publisher.national import DEFAULT_LOCATIONS, NationalConfig
from wisselweer.weather.base import ProviderInfo, ProviderUnavailable

NOW = datetime(2026, 11, 10, 8, 0, tzinfo=UTC)
START = date(2026, 11, 10)

COLD = repeat(Day(-3, 2), 16)
MILD = repeat(Day(9, 15), 16)
# Eerste koude dag over 8-9 dagen: alleen trend (periode), geen concrete datum.
LATE_COLD = repeat(Day(9, 15), 9) + repeat(Day(-3, 2), 8)

INFO = ProviderInfo(
    id="fixture",
    name="Testbron",
    attribution="Weerdata: Testbron",
    license_url="https://example.invalid/license",
    horizon_hours=240,
    commercial_use_ok=True,
)


def fc(days: list[Day], start: date = START, **kw) -> Forecast:
    return make_forecast(start, days, fetched_at=NOW, **kw)


class FakeForecasts:
    """Levert per locatienaam (via breedtegraad) een forecast, of een fout."""

    default_provider = "fixture"

    def __init__(self, by_name: dict[str, Forecast | Exception | None], default=None) -> None:
        self._by_lat = {}
        for loc in DEFAULT_LOCATIONS:
            v = by_name.get(loc.name, default)
            self._by_lat[round(loc.latitude, 4)] = v

    def get_forecast(self, latitude, longitude, provider_id=None):
        v = self._by_lat[round(latitude, 4)]
        if v is None or isinstance(v, Exception):
            raise v or ProviderUnavailable("down")
        return v

    def provider_infos(self):
        return [INFO]


def uniform(days: list[Day]) -> FakeForecasts:
    return FakeForecasts({}, default=fc(days))


CFG = NationalConfig()
NAMES = [loc.name for loc in DEFAULT_LOCATIONS]
