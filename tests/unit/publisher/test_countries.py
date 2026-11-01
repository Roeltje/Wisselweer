from __future__ import annotations

import json

import httpx
import pytest
import respx
from pydantic import ValidationError

from tests.fixtures.builders import Day, repeat
from tests.unit.publisher.helpers import COLD, INFO, MILD, NOW, fc, uniform
from wisselweer.core import PrecipType
from wisselweer.publisher.countries import build_public_countries
from wisselweer.publisher.public_schema import PublicAdvice, PublicCountry
from wisselweer.publisher.publish import run_publish
from wisselweer.regulations.loader import load_country_rules
from wisselweer.settings import Settings
from wisselweer.weather.base import ProviderUnavailable

SNOW = repeat(Day(-4, 0, 6.0, PrecipType.SNOW), 16)


class AnyForecasts:
    default_provider = "fixture"

    def __init__(self, forecast=None, error=False):
        self.forecast, self.error, self.calls = forecast, error, []

    def get_forecast(self, latitude, longitude, provider_id=None):
        self.calls.append((latitude, longitude))
        if self.error:
            raise ProviderUnavailable("down")
        return self.forecast

    def provider_infos(self):
        return [INFO]


def test_build_countries_content():
    svc = AnyForecasts(fc(SNOW))
    countries, disclaimer = build_public_countries(svc, NOW)
    by = {c.code: c for c in countries}
    assert len(countries) == 8 and "geen juridisch advies" in disclaimer
    assert by["DE"].weather.status == "winter_conditions_expected"
    assert by["DE"].weather.window_hours == 72 and len(by["DE"].weather.locations) == 6
    assert by["FR"].weather is None and by["BE"].weather is None
    assert by["AT"].period_label == "1 november – 15 april" and by["AT"].in_period is True
    assert by["DE"].period_label is None and by["DE"].in_period is None
    assert len(svc.calls) == len(set(svc.calls)) == 18


def test_mild_and_provider_failure():
    countries, _ = build_public_countries(AnyForecasts(fc(MILD)), NOW)
    assert {c.code: c for c in countries}["LU"].weather.status == "none_expected"
    countries, _ = build_public_countries(AnyForecasts(error=True), NOW)
    w = {c.code: c for c in countries}["LU"].weather
    assert w.status == "unknown" and w.locations == []


def test_no_duty_applies_now_wording():
    countries, _ = build_public_countries(AnyForecasts(fc(SNOW)), NOW)
    blob = json.dumps([c.model_dump(mode="json") for c in countries], ensure_ascii=False).lower()
    assert "nu verplicht" not in blob and "geldt nu" not in blob and "applies" not in blob


def test_public_country_extra_forbidden():
    countries, _ = build_public_countries(AnyForecasts(fc(SNOW)), NOW)
    data = countries[0].model_dump(mode="json")
    PublicCountry.model_validate(data)
    with pytest.raises(ValidationError):
        PublicCountry.model_validate(data | {"fine": "x"})
    with pytest.raises(ValidationError):
        PublicCountry.model_validate(data | {"weather": data["weather"] | {"x": 1}})


def _settings(tmp_path, **kw):
    return Settings(_env_file=None, data_dir=tmp_path / "d", publish_dir=tmp_path / "pub", **kw)


def test_publish_countries_off_no_extra_requests_and_no_field(tmp_path):
    with respx.mock(assert_all_called=False) as router:
        route = router.route().mock(return_value=httpx.Response(500))
        advice = run_publish(_settings(tmp_path), forecast_service=uniform(COLD))
        assert not route.called
    data = json.loads((tmp_path / "pub" / "advice.json").read_text())
    assert "countries" not in data and "countries_disclaimer" not in data
    assert advice.countries is None


def test_publish_countries_on(tmp_path):
    from tests.unit.publisher.helpers import FakeForecasts

    base = FakeForecasts({}, default=fc(COLD))
    svc = AnyForecasts(fc(COLD))
    svc.get_forecast = base_or_any(base, svc)  # nationale locaties uit FakeForecasts
    run_publish(_settings(tmp_path, publish_countries=True), forecast_service=svc)
    raw = (tmp_path / "pub" / "advice.json").read_text()
    parsed = PublicAdvice.model_validate_json(raw)
    assert parsed.countries and len(parsed.countries) == len(load_country_rules())
    assert parsed.countries_disclaimer
    data = json.loads(raw)
    assert data["schema_version"] == 1
    with pytest.raises(ValidationError):
        PublicAdvice.model_validate(data | {"countries": [data["countries"][0] | {"x": 1}]})
    assert set(data["countries"][0]) <= set(PublicCountry.model_fields)
    assert len(svc.calls) == 18


def base_or_any(base, svc):
    def get(latitude, longitude, provider_id=None):
        try:
            return base.get_forecast(latitude, longitude)
        except KeyError:
            svc.calls.append((latitude, longitude))
            return svc.forecast

    return get
