"""Instelling WISSELWEER_TIRE_AGE_WARN_YEARS."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from wisselweer.settings import Settings

ROOT = Path(__file__).resolve().parents[2]


def test_standaard_is_acht_jaar():
    assert Settings(_env_file=None).tire_age_warn_years == 8


def test_instelbaar_via_omgeving(monkeypatch):
    monkeypatch.setenv("WISSELWEER_TIRE_AGE_WARN_YEARS", "6.5")
    assert Settings(_env_file=None).tire_age_warn_years == 6.5
    monkeypatch.setenv("WISSELWEER_TIRE_AGE_WARN_YEARS", "")  # leeg = niet gezet
    assert Settings(_env_file=None).tire_age_warn_years == 8


@pytest.mark.parametrize("value", ["0", "-1", "31", "veel"])
def test_ongeldige_waarden_worden_geweigerd(monkeypatch, value):
    monkeypatch.setenv("WISSELWEER_TIRE_AGE_WARN_YEARS", value)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_staat_in_env_example_met_de_standaardwaarde():
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "\nWISSELWEER_TIRE_AGE_WARN_YEARS=8\n" in text
