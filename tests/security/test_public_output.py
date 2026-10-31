"""Privacy: het publieke advies bevat nooit gegevens uit de database."""

from __future__ import annotations

import json

import pytest

from tests.integration.conftest import vehicle_in
from tests.unit.publisher.helpers import COLD, uniform
from wisselweer.garages.schemas import GarageIn
from wisselweer.garages.service import create_garage
from wisselweer.publisher.public_schema import PublicAdvice
from wisselweer.publisher.publish import run_publish
from wisselweer.settings import Settings
from wisselweer.vehicles.service import create_vehicle

CONTRACT_KEYS = {
    "schema_version", "country", "locale", "next_season", "heading", "status", "status_label",
    "summary", "recommended_date", "recommended_period", "regional_variation", "regions",
    "forecast_until", "outlook", "generated_at", "stale_after", "source", "rules_version",
}  # fmt: skip


def test_public_json_contains_no_private_data(tmp_path):
    from wisselweer.storage.db import make_engine, make_session_factory, migrate, session_scope

    (tmp_path / "data").mkdir()
    url = f"sqlite:///{tmp_path / 'data' / 'wisselweer.db'}"
    migrate(url)
    factory = make_session_factory(make_engine(url))
    with session_scope(factory) as s:
        create_vehicle(s, vehicle_in(name="Geheime Testauto", plate="XX-000-X"))
        create_garage(
            s,
            GarageIn(name="Garage Privé", email="garage@example.invalid", phone="+31 6 00000000"),
        )

    settings = Settings(_env_file=None, data_dir=tmp_path / "data", publish_dir=tmp_path / "pub")
    advice = run_publish(settings, forecast_service=uniform(COLD))
    raw = (tmp_path / "pub" / "advice.json").read_text(encoding="utf-8")
    data = json.loads(raw)

    assert set(data) == CONTRACT_KEYS
    assert set(data["source"]) == {"name", "attribution", "license_url"}
    for r in data["regions"]:
        assert set(r) == {"name", "status"}
    for d in data["outlook"]:
        assert set(d) == {
            "date",
            "temp_min_c",
            "temp_max_c",
            "frost_night",
            "snow_possible",
            "kind",
        }
    for secret in (
        "XX-000-X",
        "XX000X",
        "Geheime Testauto",
        "garage@example.invalid",
        "+31 6",
        "Garage Priv",
        "Testauto",
        "example.invalid/contact",
    ):
        assert secret not in raw
    assert "latitude" not in raw and "longitude" not in raw and "52.0907" not in raw
    assert PublicAdvice.model_validate_json(raw) == advice


def test_public_model_rejects_foreign_fields():
    data = json.loads(
        PublicAdvice.model_validate_json(
            '{"next_season":"winter","heading":"h","status":"KEEP_CURRENT","status_label":"l",'
            '"summary":"s","regional_variation":false,"regions":[],'
            '"generated_at":"2026-01-01T00:00:00Z","stale_after":"2026-01-01T18:00:00Z",'
            '"source":{"name":"n","attribution":"a","license_url":"u"},"rules_version":"1"}'
        ).model_dump_json()
    )
    with pytest.raises(ValueError):
        PublicAdvice.model_validate(data | {"license_plate": "XX-000-X"})
