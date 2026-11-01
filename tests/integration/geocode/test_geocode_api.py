from __future__ import annotations

import logging

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from tests.fixtures.auth import ADMIN_PASSWORD, ADMIN_USER, bearer
from tests.integration.geocode.conftest import CONTACT, NOMINATIM, make_app
from tests.integration.web.conftest import csrf_from
from wisselweer import __version__

SEARCH = f"{NOMINATIM}/search"


def _row(name="Utrecht, Nederland", lat="52.09074", lon="5.12142"):
    return {"place_id": 1, "display_name": name, "lat": lat, "lon": lon, "type": "city"}


def test_geocode_vereist_login(anon):
    r = anon.get("/api/v1/geocode", params={"q": "Utrecht"})
    assert r.status_code == 401


@respx.mock
def test_geocode_afronden_en_vorm(client):
    route = respx.get(SEARCH).respond(
        200, json=[_row(), _row("Utrecht, Chili", "-33.45678", "-70.5")]
    )
    r = client.get("/api/v1/geocode", params={"q": "Utrecht"})
    assert r.status_code == 200
    assert r.json() == [
        {"label": "Utrecht, Nederland", "latitude": 52.091, "longitude": 5.121},
        {"label": "Utrecht, Chili", "latitude": -33.457, "longitude": -70.5},
    ]
    assert route.call_count == 1


@respx.mock
def test_geocode_begrenst_aantal_en_label(client):
    rows = [_row(name="x" * 500 + str(i)) for i in range(8)]
    respx.get(SEARCH).respond(200, json=rows)
    body = client.get("/api/v1/geocode", params={"q": "veel"}).json()
    assert len(body) == 5
    assert all(len(item["label"]) == 200 for item in body)


@respx.mock
def test_geocode_slaat_onbruikbare_rijen_over(client):
    rows = [
        _row(lat="abc"),
        _row(lat="91", lon="0"),
        _row(lon="181"),
        _row(lat="nan"),
        {"display_name": "", "lat": "1", "lon": "1"},
        "geen-object",
        _row("Goed", "-0.0001", "0"),
    ]
    respx.get(SEARCH).respond(200, json=rows)
    body = client.get("/api/v1/geocode", params={"q": "rommel"}).json()
    assert body == [{"label": "Goed", "latitude": 0.0, "longitude": 0.0}]
    assert str(body[0]["latitude"]) == "0.0"  # geen "-0.0"


@respx.mock
def test_geocode_leeg_resultaat(client):
    respx.get(SEARCH).respond(200, json=[])
    r = client.get("/api/v1/geocode", params={"q": "Nergensland"})
    assert r.status_code == 200 and r.json() == []


@respx.mock
def test_geocode_parameters_en_user_agent(client):
    route = respx.get(SEARCH).respond(200, json=[])
    client.get("/api/v1/geocode", params={"q": "  Dom  Utrecht ", "lang": "de-DE"})
    req = route.calls.last.request
    assert dict(req.url.params) == {
        "q": "Dom  Utrecht",
        "format": "jsonv2",
        "limit": "5",
        "addressdetails": "0",
        "accept-language": "de-DE",
    }
    assert req.headers["user-agent"] == (
        f"Wisselweer/{__version__} (+https://wisselweer.nl; {CONTACT})"
    )


@respx.mock
def test_geocode_standaardtaal_en_ongeldige_taal(client):
    route = respx.get(SEARCH).respond(200, json=[])
    client.get("/api/v1/geocode", params={"q": "Utrecht"})
    assert route.calls.last.request.url.params["accept-language"] == "nl-NL"
    client.get("/api/v1/geocode", params={"q": "Utrecht 2", "lang": "xx"})
    assert route.calls.last.request.url.params["accept-language"] == "nl-NL"


@respx.mock
def test_geocode_taal_van_de_sessie(app):
    route = respx.get(SEARCH).respond(200, json=[])
    with TestClient(app, raise_server_exceptions=False) as c:
        page = c.get("/login")
        r = c.post(
            "/login",
            data={
                "username": ADMIN_USER,
                "password": ADMIN_PASSWORD,
                "csrf_token": csrf_from(page.text),
                "next": "/",
            },
            follow_redirects=False,
        )
        assert r.status_code == 303
        c.get("/?lang=en")
        # Sessie-cookie volstaat voor GET (geen CSRF-token nodig).
        assert c.get("/api/v1/geocode", params={"q": "Utrecht"}).status_code == 200
    assert route.calls.last.request.url.params["accept-language"] == "en"


@pytest.mark.parametrize("q", ["", "a", " a ", "   ", "x" * 201])
def test_geocode_q_te_kort_of_te_lang(client, q):
    r = client.get("/api/v1/geocode", params={"q": q})
    assert r.status_code == 422
    assert r.json() == {
        "detail": "validation_error",
        "errors": [{"loc": ["query", "q"], "type": r.json()["errors"][0]["type"]}],
    }  # de invoer zelf wordt niet teruggestuurd


def test_geocode_q_ontbreekt(client):
    assert client.get("/api/v1/geocode").status_code == 422


@respx.mock
def test_geocode_q_precies_op_de_grenzen(client):
    respx.get(SEARCH).respond(200, json=[])
    assert client.get("/api/v1/geocode", params={"q": "ab"}).status_code == 200
    assert client.get("/api/v1/geocode", params={"q": "x" * 200}).status_code == 200


@respx.mock
@pytest.mark.parametrize("status", [429, 500, 503])
def test_geocode_upstream_status_geeft_502(client, status):
    respx.get(SEARCH).respond(status)
    r = client.get("/api/v1/geocode", params={"q": "Utrecht"})
    assert r.status_code == 502
    assert r.json() == {"detail": "geocoder_unavailable"}


@respx.mock
def test_geocode_upstream_timeout_geeft_502(client):
    respx.get(SEARCH).mock(side_effect=httpx.ConnectTimeout("te traag"))
    r = client.get("/api/v1/geocode", params={"q": "Utrecht"})
    assert r.status_code == 502
    assert r.json() == {"detail": "geocoder_unavailable"}


@respx.mock
@pytest.mark.parametrize("content", [b"geen json", b'{"a": 1}'])
def test_geocode_onbruikbaar_antwoord_geeft_502(client, content):
    respx.get(SEARCH).respond(200, content=content)
    assert client.get("/api/v1/geocode", params={"q": "Utrecht"}).status_code == 502


@respx.mock
def test_geocode_te_groot_antwoord_geeft_502(client):
    respx.get(SEARCH).respond(200, content=b"[" + b" " * (5 * 1024 * 1024 + 1) + b"]")
    assert client.get("/api/v1/geocode", params={"q": "Utrecht"}).status_code == 502


@respx.mock
def test_geocode_cache_voorkomt_tweede_upstream_call(client):
    route = respx.get(SEARCH).respond(200, json=[_row()])
    a = client.get("/api/v1/geocode", params={"q": "Utrecht"}).json()
    b = client.get("/api/v1/geocode", params={"q": "  UTRECHT "}).json()
    assert a == b and route.call_count == 1
    # Andere taal = andere sleutel.
    client.get("/api/v1/geocode", params={"q": "Utrecht", "lang": "en"})
    assert route.call_count == 2


@respx.mock
def test_geocode_cache_verloopt_na_24_uur(client, fake_time):
    route = respx.get(SEARCH).respond(200, json=[_row()])
    client.get("/api/v1/geocode", params={"q": "Utrecht"})
    fake_time.now += 24 * 3600 - 1
    client.get("/api/v1/geocode", params={"q": "Utrecht"})
    assert route.call_count == 1
    fake_time.now += 2
    client.get("/api/v1/geocode", params={"q": "Utrecht"})
    assert route.call_count == 2


@respx.mock
def test_geocode_cache_is_begrensd(client, monkeypatch):
    from wisselweer import geocoding

    monkeypatch.setattr(geocoding, "CACHE_MAX_ITEMS", 2)
    route = respx.get(SEARCH).respond(200, json=[_row()])
    for q in ("aa", "bb", "cc"):
        client.get("/api/v1/geocode", params={"q": q})
    assert route.call_count == 3
    client.get("/api/v1/geocode", params={"q": "cc"})  # nog in de cache
    assert route.call_count == 3
    client.get("/api/v1/geocode", params={"q": "aa"})  # als oudste verdrongen
    assert route.call_count == 4


@respx.mock
def test_geocode_fout_wordt_niet_gecachet(client):
    route = respx.get(SEARCH).mock(
        side_effect=[httpx.Response(500), httpx.Response(200, json=[_row()])]
    )
    assert client.get("/api/v1/geocode", params={"q": "Utrecht"}).status_code == 502
    assert client.get("/api/v1/geocode", params={"q": "Utrecht"}).status_code == 200
    assert route.call_count == 2


@respx.mock
def test_geocode_ratelimit_wacht_een_seconde(client, fake_time):
    respx.get(SEARCH).respond(200, json=[])
    client.get("/api/v1/geocode", params={"q": "Utrecht"})
    client.get("/api/v1/geocode", params={"q": "Amsterdam"})
    assert len(fake_time.slept) == 1
    assert fake_time.slept[0] == pytest.approx(1.0)


@respx.mock
def test_geocode_ratelimit_geeft_429_bij_te_lange_wachtrij(client, fake_time):
    respx.get(SEARCH).respond(200, json=[])
    statuses = []
    for i in range(5):
        r = client.get("/api/v1/geocode", params={"q": f"plaats {i}"})
        statuses.append(r.status_code)
        fake_time.now = 1000.0  # de tijd loopt niet door tussen de aanroepen
    assert statuses == [200, 200, 200, 200, 429]
    assert r.json() == {"detail": "geocoder_rate_limited"}
    assert int(r.headers["retry-after"]) >= 1


def test_geocode_uit_bij_lege_url(tmp_path, fake_time):
    app = make_app(tmp_path, geocoder_url="")
    with TestClient(app, raise_server_exceptions=False, headers=bearer(app)) as c:
        r = c.get("/api/v1/geocode", params={"q": "Utrecht"})
    assert r.status_code == 503
    assert r.json() == {"detail": "geocoder_not_configured"}


def test_geocode_uit_zonder_contact(tmp_path, fake_time):
    app = make_app(tmp_path, contact=None)
    with TestClient(app, raise_server_exceptions=False, headers=bearer(app)) as c:
        r = c.get("/api/v1/geocode", params={"q": "Utrecht"})
    assert r.status_code == 503
    assert r.json() == {"detail": "geocoder_not_configured"}


@respx.mock
def test_geocode_loopback_http_url(tmp_path, fake_time):
    route = respx.get("http://127.0.0.1:8088/search").respond(200, json=[_row()])
    app = make_app(tmp_path, geocoder_url="http://127.0.0.1:8088")
    with TestClient(app, raise_server_exceptions=False, headers=bearer(app)) as c:
        assert c.get("/api/v1/geocode", params={"q": "Utrecht"}).status_code == 200
    assert route.call_count == 1


@respx.mock
def test_zoektekst_komt_niet_in_de_logs(client, caplog):
    geheim = "Geheimstraat 12 Zoekstad"
    respx.get(SEARCH).mock(side_effect=[httpx.Response(200, json=[_row()]), httpx.Response(500)])
    with caplog.at_level(logging.DEBUG):
        assert client.get("/api/v1/geocode", params={"q": geheim}).status_code == 200
        assert client.get("/api/v1/geocode", params={"q": geheim + " fout"}).status_code == 502
    assert any("geocoder_unavailable" in r.getMessage() for r in caplog.records)
    for rec in caplog.records:
        assert "Geheimstraat" not in rec.getMessage()
        assert "Geheimstraat" not in str(rec.args)
    assert "Geheimstraat" not in caplog.text
