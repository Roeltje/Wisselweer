"""GET /api/v1/rdw: kenteken -> merk, type, bouwjaar en openstaande terugroepacties (RDW gemockt)."""

from __future__ import annotations

import logging

import httpx
import respx
from fastapi.testclient import TestClient

from tests.fixtures.auth import bearer
from tests.integration.rdw.conftest import RDW, make_app

VEH = f"{RDW}/resource/m9d7-ebf2.json"
STATUS = f"{RDW}/resource/t49b-isb7.json"
RECALLS = f"{RDW}/resource/j9yg-7rg9.json"


def _veh(**kw):
    row = {
        "kenteken": "XX123X",
        "merk": "VOLKSWAGEN",
        "handelsbenaming": "GOLF VARIANT",
        "datum_eerste_toelating": "20180315",
        "eerste_kleur": "GRIJS",
        "openstaande_terugroepactie_indicator": "Nee",
    }
    row.update(kw)
    return [row]


def test_rdw_vereist_login(anon):
    assert anon.get("/api/v1/rdw", params={"kenteken": "XX-123-X"}).status_code == 401


@respx.mock
def test_rdw_normaliseert_kenteken_en_geeft_nette_waarden(client):
    route = respx.get(VEH).respond(200, json=_veh())
    r = client.get("/api/v1/rdw", params={"kenteken": " xx-123-x "})
    assert r.status_code == 200
    assert r.json() == {
        "plate": "XX123X",
        "make": "Volkswagen",
        "model": "Golf Variant",
        "build_year": 2018,
        "color": "GRIJS",
        "open_recall": False,
        "recalls": [],
    }
    assert route.calls.last.request.url.params["kenteken"] == "XX123X"
    assert not respx.get(STATUS).called


@respx.mock
def test_rdw_haalt_openstaande_terugroepacties_op(client):
    respx.get(VEH).respond(
        200, json=_veh(merk="MERCEDES-BENZ", openstaande_terugroepactie_indicator="Ja")
    )
    respx.get(STATUS).respond(
        200,
        json=[
            {"kenteken": "XX123X", "referentiecode_rdw": "MGP220252", "code_status": "O"},
            {"kenteken": "XX123X", "referentiecode_rdw": "MGP110001", "code_status": "P"},
        ],
    )
    respx.get(RECALLS).respond(
        200,
        json=[
            {
                "referentiecode_rdw": "MGP220252",
                "omschrijving_defect": "Remleiding kan  lekken.",
                "beschrijving_van_het_herstel": "De dealer vervangt de leiding.",
                "publicatiedatum_rdw": "20220601",
            }
        ],
    )
    body = client.get("/api/v1/rdw", params={"kenteken": "XX123X"}).json()
    assert body["make"] == "Mercedes-Benz" and body["open_recall"] is True
    assert body["recalls"] == [
        {
            "reference": "MGP220252",
            "defect": "Remleiding kan lekken.",
            "remedy": "De dealer vervangt de leiding.",
            "published": "2022-06-01",
        }
    ]


@respx.mock
def test_rdw_cachet_antwoorden(client):
    route = respx.get(VEH).respond(200, json=_veh())
    client.get("/api/v1/rdw", params={"kenteken": "XX123X"})
    client.get("/api/v1/rdw", params={"kenteken": "xx-123-x"})
    assert route.call_count == 1


def test_rdw_ongeldig_kenteken_zonder_verzoek(client):
    with respx.mock(assert_all_called=False) as mock:
        route = mock.get(VEH)
        for plate in ("", "A", "AB-123-CDEFG", "<script>", "XX 1'23"):
            r = client.get("/api/v1/rdw", params={"kenteken": plate})
            assert r.status_code == 422, plate
        assert not route.called


@respx.mock
def test_rdw_onbekend_kenteken_404(client):
    respx.get(VEH).respond(200, json=[])
    r = client.get("/api/v1/rdw", params={"kenteken": "XX123X"})
    assert r.status_code == 404 and r.json() == {"detail": "rdw_not_found"}


@respx.mock
def test_rdw_fouten_geven_502_zonder_details_en_loggen_geen_kenteken(client, caplog):
    respx.get(VEH).mock(side_effect=httpx.ConnectTimeout("XX123X"))
    with caplog.at_level(logging.DEBUG):
        r = client.get("/api/v1/rdw", params={"kenteken": "XX123X"})
    assert r.status_code == 502 and r.json() == {"detail": "rdw_unavailable"}
    assert "XX123X" not in caplog.text and "rdw.example" not in caplog.text


@respx.mock
def test_rdw_onbruikbaar_antwoord_502(client):
    respx.get(VEH).respond(200, text="geen json")
    assert client.get("/api/v1/rdw", params={"kenteken": "XX123X"}).status_code == 502


def test_rdw_uitgezet_503(tmp_path):
    app = make_app(tmp_path, rdw_url="off")
    with TestClient(app, raise_server_exceptions=False, headers=bearer(app)) as c:
        r = c.get("/api/v1/rdw", params={"kenteken": "XX123X"})
    assert r.status_code == 503 and r.json() == {"detail": "rdw_disabled"}
