"""Het zoekveld en de locatieknop in de locatieformulieren (server-side sjabloonkeuze)."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from tests.integration.geocode.conftest import login_web, make_app
from tests.integration.web.conftest import create_vehicle

INLINE = [
    re.compile(r"<style", re.I),
    re.compile(r"\sstyle\s*=", re.I),
    re.compile(r"<script(?![^>]*\ssrc=)", re.I),
    re.compile(r"\son[a-z]+\s*=", re.I),
    re.compile(r"javascript:", re.I),
]


def _pages(web) -> list[str]:
    vid = create_vehicle(web)
    return ["/vehicles/new", f"/vehicles/{vid}/location"]


def test_formulieren_bevatten_zoekveld_en_vermelding_als_aan(anon):
    web = login_web(anon)
    for url in _pages(web):
        html = web.get(url).text
        assert "data-geo-search" in html and 'id="geo-q"' in html, url
        assert "Adres, postcode of plaats" in html and "Zoek coördinaten" in html
        assert "Gebruik mijn locatie" in html and "data-geo-locate" in html
        assert "Zoeken via OpenStreetMap Nominatim" in html
        assert (
            '<a href="https://www.openstreetmap.org/copyright" rel="noopener noreferrer">'
            "OpenStreetMap-bijdragers</a>"
        ) in html
        assert 'aria-live="polite"' in html
        assert 'data-url="/api/v1/geocode"' in html
        # Het zoekveld heeft geen name: de zoektekst gaat nooit met het formulier mee.
        assert not re.search(r'<input[^>]*id="geo-q"[^>]*\sname=', html)
        # Zonder JS blijven de handmatige velden gewoon staan.
        assert 'name="latitude"' in html and 'name="longitude"' in html
        for rx in INLINE:
            assert not rx.search(html), (url, rx.pattern)


def test_validatiefout_toont_ook_de_zoekhulp(anon):
    web = login_web(anon)
    r = web.post("/vehicles/new", {"name": "Auto", "latitude": "abc"})
    assert r.status_code == 422
    assert "data-geo-search" in r.text


def test_andere_formulieren_hebben_geen_zoekhulp(anon):
    web = login_web(anon)
    vid = create_vehicle(web)
    for url in ("/garages/new", f"/vehicles/{vid}/edit", f"/vehicles/{vid}/profile"):
        html = web.get(url).text
        assert "data-geo" not in html, url


def test_zoekveld_verborgen_bij_lege_url(tmp_path, fake_time):
    app = make_app(tmp_path, geocoder_url="")
    with TestClient(app, raise_server_exceptions=False) as c:
        web = login_web(c)
        for url in _pages(web):
            html = web.get(url).text
            assert "geo-q" not in html and "data-geo-search" not in html, url
            assert "openstreetmap.org/copyright" not in html
            assert "Zoek coördinaten" not in html
            # De locatieknop gebruikt de browser, niet de geocoder, en blijft beschikbaar.
            assert "data-geo-locate" in html
            assert 'name="latitude"' in html


def test_zoekveld_verborgen_zonder_contact(tmp_path, fake_time):
    app = make_app(tmp_path, contact=None)
    with TestClient(app, raise_server_exceptions=False) as c:
        web = login_web(c)
        html = web.get("/vehicles/new").text
        assert "geo-q" not in html and "data-geo-search" not in html


@pytest.mark.parametrize("lang", ["en", "de-DE"])
def test_zoekhulp_vertaald(anon, lang):
    web = login_web(anon)
    html = web.get(f"/vehicles/new?lang={lang}").text
    expected = {"en": "Address, postcode or place", "de-DE": "Adresse, Postleitzahl oder Ort"}
    assert expected[lang] in html


def test_javascript_zonder_innerhtml_en_met_same_origin_fetch(anon):
    js = anon.get("/static/app.js").text
    assert "innerHTML" not in js and "insertAdjacentHTML" not in js
    assert "/api/v1/geocode" not in js  # de URL komt uit de template (data-url)
    assert 'credentials: "same-origin"' in js
    assert "navigator" in js and "getCurrentPosition" in js
