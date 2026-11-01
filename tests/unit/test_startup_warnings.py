"""Waarschuwingen bij het opstarten van de app (configuratie die onveilig kan zijn)."""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from wisselweer.api.app import create_app, startup_warnings
from wisselweer.settings import Settings, is_loopback_host


def _settings(tmp_path, **kw) -> Settings:
    return Settings(_env_file=None, data_dir=tmp_path / "data", **kw)


@pytest.mark.parametrize(
    ("host", "loopback"),
    [
        ("127.0.0.1", True),
        ("::1", True),
        ("localhost", True),
        ("0.0.0.0", False),
        ("192.0.2.10", False),
        ("app.example.invalid", False),
    ],
)
def test_is_loopback_host(host, loopback):
    assert is_loopback_host(host) is loopback


@pytest.mark.parametrize("host", ["0.0.0.0", "192.0.2.10"])
def test_waarschuwt_bij_niet_loopback_zonder_secure_cookie(tmp_path, host):
    (waarschuwing,) = startup_warnings(_settings(tmp_path, host=host))
    assert "WISSELWEER_COOKIE_SECURE=true" in waarschuwing


def test_geen_cookiewaarschuwing_bij_loopback_of_secure(tmp_path):
    assert startup_warnings(_settings(tmp_path)) == []
    assert startup_warnings(_settings(tmp_path, host="0.0.0.0", cookie_secure=True)) == []


def test_waarschuwing_wordt_gelogd_bij_start(tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger="wisselweer.api"):
        with TestClient(create_app(_settings(tmp_path, host="0.0.0.0"))):
            pass
    assert any("COOKIE_SECURE" in r.getMessage() for r in caplog.records)
