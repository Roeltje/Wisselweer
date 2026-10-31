"""Genereert de JSON-voorbeeldresponses in docs/examples/ uit de echte API.

Gebruik: `uv run python scripts/generate_examples.py`
Geen netwerk: een fake weerprovider levert een vaste, fictieve forecast. Alle data is fictief.
Tijdstempels, id's en datums hangen af van het moment van draaien.
"""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import UTC, date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from tests.fixtures.auth import bearer  # noqa: E402
from tests.fixtures.builders import Day, make_forecast, repeat  # noqa: E402
from wisselweer.api.app import create_app  # noqa: E402
from wisselweer.api.deps import ensure_db, get_forecast_service  # noqa: E402
from wisselweer.settings import Settings  # noqa: E402
from wisselweer.storage.cache_backend import SqliteCacheBackend  # noqa: E402
from wisselweer.weather.base import FetchResult, ProviderInfo  # noqa: E402
from wisselweer.weather.cache import ForecastCache  # noqa: E402
from wisselweer.weather.service import ForecastService  # noqa: E402

API = "/api/v1"
OUT = ROOT / "docs" / "examples"


class FakeProvider:
    def info(self) -> ProviderInfo:
        return ProviderInfo(
            id="fake",
            name="Fake",
            attribution="Fictieve data",
            license_url="https://example.invalid/license",
            horizon_hours=240,
            commercial_use_ok=True,
        )

    def fetch(self, lat, lon, *, if_modified_since=None):
        fc = make_forecast(
            date.today(),
            repeat(Day(-6, 0), 10),
            fetched_at=datetime.now(UTC),
            provider="fake",
        )
        return FetchResult(forecast=fc)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        app = create_app(Settings(_env_file=None, data_dir=Path(tmp) / "data"))
        factory = ensure_db(app)
        service = ForecastService(
            {"fake": FakeProvider()}, ForecastCache(SqliteCacheBackend(factory)), "fake"
        )
        app.dependency_overrides[get_forecast_service] = lambda: service
        with TestClient(app, headers=bearer(app)) as c:
            vehicle = c.post(
                f"{API}/vehicles",
                json={
                    "name": "Testauto",
                    "license_plate": "XX-000-X",
                    "location": {"name": "Utrecht", "latitude": 52.0907, "longitude": 5.1214},
                },
            )
            vehicle.raise_for_status()
            vid = vehicle.json()["id"]
            summer = c.post(
                f"{API}/vehicles/{vid}/tire-sets", json={"type": "summer", "status": "mounted"}
            ).json()
            winter = c.post(f"{API}/vehicles/{vid}/tire-sets", json={"type": "winter"}).json()
            advice = c.get(f"{API}/vehicles/{vid}/advice")
            advice.raise_for_status()
            change = c.post(
                f"{API}/vehicles/{vid}/tire-changes",
                json={
                    "to_set_id": winter["id"],
                    "changed_at": date.today().isoformat(),
                    "odometer_km": 42000,
                },
            )
            change.raise_for_status()
            assert summer["id"] != winter["id"]
            files = {
                "vehicle-advice.json": advice.json(),
                "vehicle.json": vehicle.json(),
                "tire-change.json": change.json(),
            }
    for name, body in files.items():
        (OUT / name).write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n")
        print(f"geschreven: docs/examples/{name}")


if __name__ == "__main__":
    main()
