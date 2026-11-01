"""Validatie van instellingen: secret key."""

from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from wisselweer.settings import Settings


def test_secret_key_leeg_of_afwezig_mag():
    assert Settings(_env_file=None).secret_key is None
    assert Settings(_env_file=None, secret_key="").secret_key is None
    assert Settings(_env_file=None, secret_key=SecretStr("")).secret_key is None


def test_secret_key_leeg_in_omgeving_mag(monkeypatch):
    monkeypatch.setenv("WISSELWEER_SECRET_KEY", "")
    assert Settings(_env_file=None).secret_key is None


@pytest.mark.parametrize("lengte", [32, 33, 64])
def test_secret_key_lang_genoeg(lengte):
    key = "k" * lengte
    assert Settings(_env_file=None, secret_key=key).secret_key.get_secret_value() == key


@pytest.mark.parametrize("lengte", [2, 16, 31])
def test_secret_key_te_kort(lengte):
    geheim = "Q9" + "z" * (lengte - 2)
    with pytest.raises(ValidationError) as ei:
        Settings(_env_file=None, secret_key=geheim)
    tekst = str(ei.value)
    assert "WISSELWEER_SECRET_KEY" in tekst and "32" in tekst
    assert geheim not in tekst  # de waarde komt niet in de foutmelding


def test_secret_key_te_kort_uit_omgeving(monkeypatch):
    monkeypatch.setenv("WISSELWEER_SECRET_KEY", "kort")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
