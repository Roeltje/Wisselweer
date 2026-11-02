"""Voertuigformulier: kenteken bovenaan met de RDW-knop (server-side sjabloonkeuze)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.integration.geocode.conftest import login_web
from tests.integration.rdw.conftest import make_app
from tests.integration.web.conftest import create_vehicle


def test_kenteken_staat_bovenaan_met_rdw_knop(anon):
    web = login_web(anon)
    vid = create_vehicle(web)
    for url in ("/vehicles/new", f"/vehicles/{vid}/edit"):
        html = web.get(url).text
        names = [
            n
            for n in ("license_plate", "name", "make", "model", "build_year")
            if f'name="{n}"' in html
        ]
        assert names == ["license_plate", "name", "make", "model", "build_year"], url
        assert (
            html.index('name="license_plate"') < html.index("data-rdw") < html.index('name="name"')
        )
        assert 'data-url="/api/v1/rdw"' in html and "Gegevens ophalen bij RDW" in html
        assert "data-rdw hidden" in html  # zonder JavaScript onzichtbaar


def test_geen_rdw_knop_als_uitgezet(tmp_path):
    app = make_app(tmp_path, rdw_url="off")
    with TestClient(app, raise_server_exceptions=False) as anon:
        html = login_web(anon).get("/vehicles/new").text
    assert "data-rdw" not in html and 'name="license_plate"' in html


def test_app_js_gebruikt_alleen_textcontent_voor_rdw():
    from pathlib import Path

    js = (Path(__file__).parents[3] / "src/wisselweer/web/static/app.js").read_text(
        encoding="utf-8"
    )
    block = js.split("var rdw = document.querySelector", 1)[1]
    assert "innerHTML" not in block and "insertAdjacentHTML" not in block
