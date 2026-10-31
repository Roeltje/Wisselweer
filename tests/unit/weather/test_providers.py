from datetime import UTC, datetime

import httpx
import pytest
import respx

from tests.unit.weather.helpers import load
from wisselweer.core.models import PrecipType
from wisselweer.observations.wunderground import WundergroundProvider
from wisselweer.weather.base import (
    ForecastProvider,
    ProviderNotConfigured,
    ProviderRateLimited,
    ProviderUnavailable,
)
from wisselweer.weather.brightsky import BrightSkyObservationProvider, BrightSkyProvider
from wisselweer.weather.knmi import KnmiForecastProvider, KnmiObservationProvider
from wisselweer.weather.metno import MetNoProvider
from wisselweer.weather.openmeteo import OpenMeteoProvider

MET = "https://api.met.no/weatherapi/locationforecast/2.0/complete"
OM = "https://api.open-meteo.com/v1/forecast"
BS = "https://api.brightsky.dev/weather"
BSC = "https://api.brightsky.dev/current_weather"
WU = "https://api.weather.com/v2/pws/observations/current"
KNMI = "https://api.dataplatform.knmi.nl/edr/v1/collections/10-minute-in-situ-meteorological-observations/locations/0-20000-0-06260"


# ---- MET Norway
@respx.mock
def test_metno_normalises():
    route = respx.get(MET).respond(
        200,
        json=load("metno_complete.json"),
        headers={
            "Expires": "Sun, 01 Nov 2026 07:00:00 GMT",
            "Last-Modified": "Sun, 01 Nov 2026 06:00:00 GMT",
        },
    )
    p = MetNoProvider("garage@example.invalid")
    res = p.fetch(52.123456, 5.987654)
    req = route.calls.last.request
    assert req.url.params["lat"] == "52.1235" and req.url.params["lon"] == "5.9877"
    assert req.headers["user-agent"].startswith("Wisselweer/0.1.0 (+https://wisselweer.nl; garage@")
    fc = res.forecast
    assert fc.timezone == "Europe/Amsterdam"
    assert res.expires == datetime(2026, 11, 1, 7, tzinfo=UTC)
    assert res.last_modified.startswith("Sun, 01 Nov")
    assert [x.precip_type for x in fc.hourly] == [
        PrecipType.SNOW,
        PrecipType.NONE,
        PrecipType.SLEET,
        PrecipType.UNKNOWN,
    ]
    assert fc.hourly[0].temperature_c == 2.1
    assert fc.hourly[1].dew_point_c is None  # niet geleverd
    assert fc.hourly[2].precip_mm is None  # 6-uurstap: geen uurneerslag
    assert "precip_mm" in fc.available_variables
    assert "snow_cm" not in fc.available_variables
    assert "precip_probability_pct" not in fc.available_variables


@respx.mock
def test_metno_304():
    route = respx.get(MET).respond(304, headers={"Expires": "Sun, 01 Nov 2026 08:00:00 GMT"})
    res = MetNoProvider("c@example.invalid").fetch(
        52, 5, if_modified_since="Sun, 01 Nov 2026 06:00:00 GMT"
    )
    assert res.not_modified and res.forecast is None and res.expires.hour == 8
    assert route.calls.last.request.headers["if-modified-since"].startswith("Sun")


def test_metno_not_configured():
    p = MetNoProvider(None)
    i = p.info()
    assert not i.configured and i.status_detail == "provider.missing_contact"
    assert "CC BY 4.0" in i.attribution
    with pytest.raises(ProviderNotConfigured):
        p.fetch(52, 5)
    assert isinstance(p, ForecastProvider)


@respx.mock
def test_metno_errors():
    p = MetNoProvider("c@example.invalid")
    respx.get(MET).respond(429, headers={"Retry-After": "120"})
    with pytest.raises(ProviderRateLimited) as ei:
        p.fetch(52, 5)
    assert ei.value.retry_after is not None
    respx.get(MET).respond(503)
    with pytest.raises(ProviderUnavailable):
        p.fetch(52, 5)
    respx.get(MET).mock(side_effect=httpx.ConnectTimeout("boom"))
    with pytest.raises(ProviderUnavailable):
        p.fetch(52, 5)


# ---- Open-Meteo
@respx.mock
def test_openmeteo_normalises():
    route = respx.get(OM).respond(200, json=load("openmeteo_forecast.json"))
    fc = OpenMeteoProvider().fetch(52.09, 5.12).forecast
    q = route.calls.last.request.url.params
    assert q["forecast_days"] == "16" and q["wind_speed_unit"] == "ms"
    h = fc.hourly
    assert h[0].time == datetime(2026, 11, 1, 0, tzinfo=UTC)
    assert [x.precip_type for x in h] == [
        PrecipType.NONE,
        PrecipType.SNOW,
        PrecipType.FREEZING_RAIN,
    ]
    assert h[1].snow_depth_cm == pytest.approx(1.0)
    assert h[2].temperature_c is None and h[2].precip_probability_pct is None
    assert "snow_depth_cm" in fc.available_variables


@respx.mock
def test_openmeteo_missing_variables_stay_none():
    respx.get(OM).respond(200, json=load("openmeteo_minimal.json"))
    fc = OpenMeteoProvider().fetch(52, 5).forecast
    assert fc.available_variables == {"temperature_c"}
    assert fc.hourly[0].precip_mm is None and fc.hourly[0].precip_type is None


def test_openmeteo_commercial_guard():
    p = OpenMeteoProvider(commercial=True)
    i = p.info()
    assert not i.configured and i.status_detail == "provider.openmeteo_noncommercial"
    assert not i.commercial_use_ok
    with pytest.raises(ProviderNotConfigured):
        p.fetch(52, 5)
    assert OpenMeteoProvider(commercial=True, api_key="test-key").info().configured
    own = OpenMeteoProvider("https://om.example.invalid", commercial=True).info()
    assert own.configured and own.commercial_use_ok
    free = OpenMeteoProvider().info()
    assert free.configured and not free.commercial_use_ok


@respx.mock
def test_openmeteo_key_sent_but_not_in_errors(caplog):
    respx.get("https://customer-api.open-meteo.com/v1/forecast").respond(500)
    p = OpenMeteoProvider(
        "https://customer-api.open-meteo.com", api_key="test-key", commercial=True
    )
    with pytest.raises(ProviderUnavailable) as ei:
        p.fetch(52, 5)
    assert "test-key" not in str(ei.value)
    assert "test-key" not in caplog.text


@respx.mock
def test_openmeteo_429_and_network():
    respx.get(OM).respond(429)
    with pytest.raises(ProviderRateLimited):
        OpenMeteoProvider().fetch(52, 5)
    respx.get(OM).mock(side_effect=httpx.ConnectError("x"))
    with pytest.raises(ProviderUnavailable):
        OpenMeteoProvider().fetch(52, 5)


# ---- Bright Sky
@respx.mock
def test_brightsky_forecast():
    respx.get(BS).respond(200, json=load("brightsky_weather.json"))
    fc = BrightSkyProvider().fetch(52.09, 5.12).forecast
    assert fc.hourly[0].wind_speed_ms == pytest.approx(5.0)  # 18 km/u
    assert [x.precip_type for x in fc.hourly] == [PrecipType.RAIN, PrecipType.SNOW, None]
    assert fc.hourly[1].dew_point_c is None
    assert "snow_cm" not in fc.available_variables
    assert "Deutscher Wetterdienst" in BrightSkyProvider().info().attribution


@respx.mock
def test_brightsky_errors():
    respx.get(BS).respond(429)
    with pytest.raises(ProviderRateLimited):
        BrightSkyProvider().fetch(52, 5)
    respx.get(BS).respond(502)
    with pytest.raises(ProviderUnavailable):
        BrightSkyProvider().fetch(52, 5)


@respx.mock
def test_brightsky_current():
    respx.get(BSC).respond(200, json=load("brightsky_current.json"))
    (o,) = BrightSkyObservationProvider(52.09, 5.12).latest()
    assert o.station_id == "4711" and o.wind_speed_ms == pytest.approx(10.0)
    assert o.precip_rate_mm_h == pytest.approx(0.6) and o.pressure_hpa == 1012.3
    assert o.latitude == 52.1


# ---- KNMI
@respx.mock
def test_knmi_observation():
    route = respx.get(KNMI).respond(200, json=load("knmi_10min.json"))
    (o,) = KnmiObservationProvider("test-key", "0-20000-0-06260").latest()
    assert route.calls.last.request.headers["authorization"] == "test-key"
    assert o.temperature_c == 3.2 and o.humidity_pct == 82 and o.wind_speed_ms == 3.0
    assert o.dew_point_c is None and o.pressure_hpa is None
    assert o.observed_at == datetime(2026, 11, 1, 6, 50, tzinfo=UTC)


def test_knmi_not_configured():
    i = KnmiObservationProvider(None, "x").info()
    assert not i.configured and i.needs_credentials
    with pytest.raises(ProviderNotConfigured):
        KnmiObservationProvider(None, "x").latest()
    assert (
        KnmiObservationProvider("test-key", None).info().status_detail
        == "provider.knmi_missing_station"
    )


@respx.mock
def test_knmi_errors_hide_key():
    respx.get(KNMI).respond(403)
    with pytest.raises(ProviderUnavailable) as ei:
        KnmiObservationProvider("test-key", "0-20000-0-06260").latest()
    assert "test-key" not in str(ei.value)
    respx.get(KNMI).respond(429, headers={"Retry-After": "5"})
    with pytest.raises(ProviderRateLimited):
        KnmiObservationProvider("test-key", "0-20000-0-06260").latest()


def test_knmi_forecast_honest():
    p = KnmiForecastProvider("test-key")
    i = p.info()
    assert not i.configured and i.status_detail == "provider.knmi_forecast_not_available"
    with pytest.raises(ProviderNotConfigured):
        p.fetch(52, 5)


# ---- Weather Underground
@respx.mock
def test_wunderground():
    route = respx.get(WU).respond(200, json=load("wunderground_current.json"))
    (o,) = WundergroundProvider("ITEST000", "test-key").latest()
    q = route.calls.last.request.url.params
    assert q["units"] == "m" and q["format"] == "json"
    assert o.wind_speed_ms == pytest.approx(5.0) and o.temperature_c == 4.1
    assert o.observed_at == datetime(2026, 11, 1, 6, 55, tzinfo=UTC)


@respx.mock
def test_wunderground_errors_and_config():
    assert not WundergroundProvider(None, "k").info().configured
    with pytest.raises(ProviderNotConfigured):
        WundergroundProvider("S", None).latest()
    respx.get(WU).respond(401)
    with pytest.raises(ProviderUnavailable) as ei:
        WundergroundProvider("ITEST000", "test-key").latest()
    assert "test-key" not in str(ei.value)
    respx.get(WU).respond(204)
    assert WundergroundProvider("ITEST000", "test-key").latest() == []
