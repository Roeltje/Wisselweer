from __future__ import annotations

import json
from pathlib import Path
from tempfile import mkdtemp

from fastapi.testclient import TestClient

from tests.fixtures.auth import bearer
from tests.unit.publisher.helpers import COLD, uniform
from wisselweer import cli
from wisselweer.api.app import create_app
from wisselweer.api.deps import get_forecast_service
from wisselweer.publisher import publish
from wisselweer.publisher.public_schema import PublicAdvice
from wisselweer.settings import Settings


def _app():
    app = create_app(Settings(_env_file=None, data_dir=Path(mkdtemp()) / "data"))
    app.dependency_overrides[get_forecast_service] = lambda: uniform(COLD)
    return app


def test_public_preview_requires_login_and_validates():
    app = _app()
    assert TestClient(app, raise_server_exceptions=False).get(
        "/api/v1/public-preview"
    ).status_code in (
        401,
        403,
    )
    r = TestClient(app, headers=bearer(app)).get("/api/v1/public-preview")
    assert r.status_code == 200
    PublicAdvice.model_validate(r.json())


def test_publish_dir_default_and_settings_override():
    s = Settings(_env_file=None, data_dir=Path("/x/data"))
    assert s.publish_dir == Path("/x/data/public")
    s = Settings(
        _env_file=None,
        national_locations=[{"name": "A", "latitude": 52.0, "longitude": 5.0}],  # type: ignore[list-item]
    )
    assert [loc.name for loc in s.national_config().locations] == ["A"]


def test_cli_publish_exit_codes(monkeypatch, tmp_path, capsys):
    settings = Settings(_env_file=None, data_dir=tmp_path / "d")
    monkeypatch.setattr("wisselweer.settings.get_settings", lambda: settings)
    monkeypatch.setattr(publish, "build_default_forecast_service", lambda s: uniform(COLD))
    assert cli.main(["publish"]) == 0
    assert json.loads((tmp_path / "d" / "public" / "advice.json").read_text())["status"]

    def boom(s, forecast_service=None):
        raise publish.PublishError("kapot")

    monkeypatch.setattr(publish, "run_publish", boom)
    assert cli.main(["publish"]) == 1
    assert "kapot" in capsys.readouterr().err
