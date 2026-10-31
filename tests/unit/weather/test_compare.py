from datetime import UTC, datetime

from wisselweer.core.models import Forecast, HourlyPoint
from wisselweer.weather.compare import compare_forecasts


def mk(provider, pts):
    return Forecast(
        provider=provider,
        latitude=52,
        longitude=5,
        timezone="Europe/Amsterdam",
        fetched_at=datetime(2026, 11, 1, tzinfo=UTC),
        hourly=[
            HourlyPoint(time=datetime(2026, 11, 1, h, tzinfo=UTC), temperature_c=t, precip_mm=p)
            for h, t, p in pts
        ],
    )


def test_compare_per_day_and_spread():
    a = mk("a", [(10, 2.0, 0.5), (12, 6.0, 0.5)])
    b = mk("b", [(10, 3.0, None), (12, 5.0, None)])
    (d,) = compare_forecasts([a, b], "Europe/Amsterdam")
    assert d.providers["a"].temp_max_c == 6.0 and d.providers["a"].precip_mm == 1.0
    assert d.providers["b"].precip_mm is None
    assert d.temp_min_spread_c == 1.0 and d.temp_max_spread_c == 1.0
    assert d.precip_spread_mm is None  # één provider met neerslagdata


def test_compare_local_day_boundary():
    # 23:30 UTC is 00:30 lokale tijd de volgende dag (CET)
    f = Forecast(
        provider="a",
        latitude=52,
        longitude=5,
        timezone="Europe/Amsterdam",
        fetched_at=datetime(2026, 11, 1, tzinfo=UTC),
        hourly=[HourlyPoint(time=datetime(2026, 11, 1, 23, 30, tzinfo=UTC), temperature_c=1.0)],
    )
    (d,) = compare_forecasts([f], "Europe/Amsterdam")
    assert d.day.isoformat() == "2026-11-02"
