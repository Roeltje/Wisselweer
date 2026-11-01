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


# ---- geocoder-URL


def test_geocoder_url_standaard_is_nominatim():
    s = Settings(_env_file=None)
    assert s.geocoder_url == "https://nominatim.openstreetmap.org"


@pytest.mark.parametrize("waarde", ["", "  ", "off", "OFF", "none", "uit"])
def test_geocoder_url_uit(waarde):
    s = Settings(_env_file=None, geocoder_url=waarde, contact="https://example.invalid/contact")
    assert s.geocoder_url == ""
    assert s.geocoding_enabled is False


@pytest.mark.parametrize(
    "url",
    ["http://geocoder.example.invalid", "ftp://example.invalid", "nominatim.example.invalid"],
)
def test_geocoder_url_http_geweigerd(url):
    with pytest.raises(ValidationError) as ei:
        Settings(_env_file=None, geocoder_url=url)
    assert "WISSELWEER_GEOCODER_URL" in str(ei.value)


@pytest.mark.parametrize(
    "url", ["http://localhost:8080", "http://127.0.0.1:8088", "http://[::1]:8088/"]
)
def test_geocoder_url_loopback_http_mag(url):
    assert Settings(_env_file=None, geocoder_url=url).geocoder_url == url.rstrip("/")


def test_geocoder_url_slash_aan_het_eind_wordt_verwijderd():
    s = Settings(_env_file=None, geocoder_url="https://nominatim.example.invalid/")
    assert s.geocoder_url == "https://nominatim.example.invalid"


def test_geocoder_url_uit_via_omgeving(monkeypatch):
    monkeypatch.setenv("WISSELWEER_GEOCODER_URL", "off")
    assert Settings(_env_file=None).geocoder_url == ""


@pytest.mark.parametrize(
    ("contact", "aan"),
    [(None, False), ("", False), ("  ", False), ("https://example.invalid/contact", True)],
)
def test_geocoderen_vereist_contact(contact, aan):
    s = Settings(_env_file=None, contact=contact)
    assert s.geocoding_enabled is aan
