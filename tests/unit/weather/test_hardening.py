"""Providers: https afdwingen, station-ID's quoten en responsegrootte begrenzen."""

from __future__ import annotations

import gzip

import httpx
import pytest
import respx
from pydantic import ValidationError

from tests.unit.weather.helpers import load
from wisselweer.observations.wunderground import WundergroundProvider
from wisselweer.settings import Settings
from wisselweer.weather._util import MAX_RESPONSE_BYTES, http_get
from wisselweer.weather.base import ProviderUnavailable
from wisselweer.weather.knmi import COLLECTION, EDR_BASE, KnmiObservationProvider

WU = "https://api.weather.com/v2/pws/observations/current"


# ---- https afdwingen voor WISSELWEER_OPENMETEO_BASE_URL
@pytest.mark.parametrize(
    "url",
    [
        "https://api.open-meteo.com",
        "https://om.example.invalid/prefix",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "http://[::1]:8080",
    ],
)
def test_openmeteo_base_url_toegestaan(url):
    assert Settings(_env_file=None, openmeteo_base_url=url).openmeteo_base_url == url


@pytest.mark.parametrize(
    "url",
    [
        "http://api.open-meteo.com",
        "http://om.example.invalid",
        "http://localhost.example.invalid",
        "http://192.0.2.10:8080",
        "ftp://om.example.invalid",
        "api.open-meteo.com",
        "https://",
        "",
    ],
)
def test_openmeteo_base_url_geweigerd(url):
    with pytest.raises(ValidationError) as ei:
        Settings(_env_file=None, openmeteo_base_url=url)
    assert "https://" in str(ei.value) and "OPENMETEO_BASE_URL" in str(ei.value)


def test_openmeteo_base_url_uit_omgeving(monkeypatch):
    monkeypatch.setenv("WISSELWEER_OPENMETEO_BASE_URL", "http://om.example.invalid")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


# ---- station-ID's quoten
@respx.mock
def test_knmi_station_id_wordt_gequote_in_pad():
    base = f"{EDR_BASE}/collections/{COLLECTION}/locations/"
    route = respx.get(url__startswith=base).respond(200, json=load("knmi_10min.json"))
    KnmiObservationProvider("test-key", "a/b?c#d e").latest()
    req = route.calls.last.request
    assert req.url.raw_path.startswith(
        f"{base.removeprefix('https://api.dataplatform.knmi.nl')}a%2Fb%3Fc%23d%20e?".encode()
    )
    assert req.url.fragment == ""
    assert "c" not in req.url.params  # niet als query geïnterpreteerd


@respx.mock
def test_wunderground_station_id_blijft_een_parameter():
    route = respx.get(WU).respond(200, json=load("wunderground_current.json"))
    WundergroundProvider("A&units=e#x", "test-key").latest()
    req = route.calls.last.request
    assert req.url.params["stationId"] == "A&units=e#x"
    assert req.url.params["units"] == "m"  # niet overschreven door de ID


# ---- responsegrootte
def _client_met(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_response_binnen_grens_komt_terug():
    client = _client_met(lambda r: httpx.Response(200, json={"ok": True}))
    resp = http_get(client, "https://example.invalid/x", provider="test")
    assert resp.json() == {"ok": True} and resp.status_code == 200


def test_response_gzip_wordt_gedecodeerd():
    body = gzip.compress(b'{"ok": true}')
    client = _client_met(
        lambda r: httpx.Response(200, content=body, headers={"Content-Encoding": "gzip"})
    )
    assert http_get(client, "https://example.invalid/x", provider="test").json() == {"ok": True}


def test_response_te_groot_volgens_content_length():
    def handler(request):
        return httpx.Response(200, content=b"{}", headers={"Content-Length": str(10 * 2**20)})

    # MockTransport valideert de header niet; echte servers kunnen dit wel sturen.
    with pytest.raises(ProviderUnavailable, match="te groot"):
        http_get(_client_met(handler), "https://example.invalid/x", provider="test")


def test_response_te_groot_zonder_content_length():
    def stream():
        for _ in range(8):
            yield b"x" * (1024 * 1024)

    client = _client_met(lambda r: httpx.Response(200, content=stream()))
    with pytest.raises(ProviderUnavailable, match="te groot"):
        http_get(client, "https://example.invalid/x", provider="test")


def test_response_te_groot_na_decompressie():
    body = gzip.compress(b"0" * (MAX_RESPONSE_BYTES + 1024))
    assert len(body) < 100_000  # klein op de draad, groot na uitpakken
    client = _client_met(
        lambda r: httpx.Response(200, content=body, headers={"Content-Encoding": "gzip"})
    )
    with pytest.raises(ProviderUnavailable, match="te groot"):
        http_get(client, "https://example.invalid/x", provider="test")


def test_foutstatus_wordt_niet_gelezen_maar_gemapt():
    client = _client_met(lambda r: httpx.Response(503, content=b"x" * 100))
    with pytest.raises(ProviderUnavailable, match="HTTP-status 503"):
        http_get(client, "https://example.invalid/x", provider="test")
