"""Webformulieren en setpagina voor banden per groep."""

from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy import select

from tests.integration.web.conftest import create_vehicle
from wisselweer.api.deps import ensure_db
from wisselweer.storage.orm import TireGroup, TireSet

WEB = Path(__file__).parents[3] / "src" / "wisselweer" / "web"


def _groups(web, set_id: int) -> list[TireGroup]:
    with ensure_db(web.c.app)() as s:
        return list(
            s.scalars(
                select(TireGroup).where(TireGroup.tire_set_id == set_id).order_by(TireGroup.id)
            )
        )


def _new_set(web, vid: int, **data) -> int:
    body = {"type": "winter", "status": "stored", **data}
    r = web.post(f"/vehicles/{vid}/sets/new", body)
    assert r.status_code == 303, r.text[:2000]
    with ensure_db(web.c.app)() as s:
        return s.scalars(select(TireSet.id).order_by(TireSet.id.desc())).first()


def test_formulier_heeft_een_standaardregel_en_drie_ingeklapte_extra_regels(web):
    vid = create_vehicle(web)
    html = web.get(f"/vehicles/{vid}/sets/new").text
    assert 'name="g1_quantity"' in html and 'value="4"' in html.split('name="g1_quantity"')[1][:80]
    assert 'name="g1_dot_code"' in html and 'name="g1_purchase_date"' in html
    # Merk en model gelden voor de set; alleen de extra regels kunnen afwijken.
    assert 'name="g1_brand"' not in html and 'name="g2_brand"' in html
    assert html.count("data-group-extra") == 3
    assert not re.search(r"<details[^>]*data-group-extra[^>]*\bopen\b", html)  # ingeklapt
    assert "+ Afwijkende banden toevoegen" in html
    # Zonder JavaScript: gewone <details> in het formulier, geen verborgen velden.
    assert re.search(r"<details[^>]*data-group-extra", html)
    assert "hidden" not in re.search(r"<details[^>]*data-group-extra[^>]*>", html).group(0)


def test_set_aanmaken_met_alleen_de_standaardregel(web):
    vid = create_vehicle(web)
    # Ook zonder groepsvelden (oudere formulieren) krijgt de set één groep van 4.
    sid = _new_set(web, vid)
    assert [(g.quantity, g.dot_code) for g in _groups(web, sid)] == [(4, None)]
    sid = _new_set(web, vid, g1_dot_code="DOT 4KXH 2319", g1_purchase_date="2020-10-01")
    (g,) = _groups(web, sid)
    assert (g.quantity, g.dot_code, str(g.purchase_date)) == (4, "DOT 4KXH 2319", "2020-10-01")


def test_set_aanmaken_met_extra_regels(web):
    vid = create_vehicle(web)
    sid = _new_set(
        web,
        vid,
        brand="Michelin",
        g1_quantity="2",
        g1_dot_code="2319",
        g2_quantity="1",
        g2_dot_code="1224",
        g2_brand="Dunlop",
        g2_model="Winter Sport 5",
        g2_positions="LV",
        g4_quantity="1",
        g4_dot_code="1225",
    )
    groups = _groups(web, sid)
    assert [(g.quantity, g.dot_code, g.brand, g.positions) for g in groups] == [
        (2, "2319", None, None),
        (1, "1224", "Dunlop", "FL"),
        (1, "1225", None, None),
    ]
    page = web.get(f"/vehicles/{vid}/sets/{sid}").text
    assert "Dunlop Winter Sport 5" in page and "zoals de set" in page and "LV" in page


def test_formulier_valideert_groepen(web):
    vid = create_vehicle(web)
    # Totaal boven 4: duidelijke melding, formulier blijft gevuld en extra regel staat open.
    r = web.post(
        f"/vehicles/{vid}/sets/new",
        {
            "type": "winter",
            "status": "stored",
            "g1_quantity": "4",
            "g2_quantity": "2",
            "g2_dot_code": "2319",
        },
    )
    assert r.status_code == 422
    assert "hooguit 4 banden" in r.text
    assert re.search(r"<details[^>]*data-group-extra[^>]*\bopen\b", r.text)
    assert 'value="2319"' in r.text
    # Een extra regel zonder aantal.
    r = web.post(
        f"/vehicles/{vid}/sets/new",
        {"type": "winter", "status": "stored", "g1_quantity": "2", "g2_dot_code": "2319"},
    )
    assert r.status_code == 422 and 'id="e-g2_quantity"' in r.text
    # Aantal buiten 1-4 en een ongeldige positie.
    r = web.post(
        f"/vehicles/{vid}/sets/new",
        {"type": "winter", "status": "stored", "g1_quantity": "5"},
    )
    assert r.status_code == 422 and 'id="e-g1_quantity"' in r.text
    r = web.post(
        f"/vehicles/{vid}/sets/new",
        {
            "type": "winter",
            "status": "stored",
            "g1_quantity": "2",
            "g2_quantity": "2",
            "g2_positions": "XX",
        },
    )
    assert r.status_code == 422 and 'id="e-g2_positions"' in r.text
    with ensure_db(web.c.app)() as s:
        assert s.scalar(select(TireSet.id)) is None  # niets half opgeslagen


def test_setpagina_toont_leeftijd_en_waarschuwingen(web):
    vid = create_vehicle(web)
    sid = _new_set(
        web, vid, g1_quantity="2", g1_dot_code="0110", g2_quantity="1", g2_dot_code="2323"
    )
    page = web.get(f"/vehicles/{vid}/sets/{sid}").text
    assert "Oudste band" in page and "jaar" in page
    assert "chip-warn" in page  # DOT 0110 (2010) is ouder dan de grens
    assert "3 banden geregistreerd in plaats van 4" in page  # som is niet 4
    overview = web.get(f"/vehicles/{vid}").text
    assert "Oudste band" in overview and "3 banden geregistreerd" in overview
    # Een onleesbare DOT-code geeft geen leeftijd en geen fout.
    sid2 = _new_set(web, vid, g1_dot_code="onleesbaar")
    page2 = web.get(f"/vehicles/{vid}/sets/{sid2}").text
    assert "Onbekend: de DOT-code ontbreekt" in page2 and "chip-warn" not in page2


def test_waarschuwingsgrens_is_instelbaar(web):
    web.c.app.state.settings.tire_age_warn_years = 100.0
    vid = create_vehicle(web)
    sid = _new_set(web, vid, g1_dot_code="0110")
    assert "chip-warn" not in web.get(f"/vehicles/{vid}/sets/{sid}").text


def test_groep_wijzigen_toevoegen_en_verwijderen(web):
    vid = create_vehicle(web)
    sid = _new_set(web, vid, g1_quantity="2", g1_dot_code="2319")
    (g1,) = _groups(web, sid)
    base = f"/vehicles/{vid}/sets/{sid}"
    assert web.get(f"{base}/groups/{g1.id}/edit").status_code == 200
    r = web.post(f"{base}/groups/{g1.id}/edit", {"quantity": "2", "dot_code": "1224", "brand": "X"})
    assert r.status_code == 303
    g1 = _groups(web, sid)[0]
    assert (g1.dot_code, g1.brand) == ("1224", "X")
    # Toevoegen: standaard het aantal dat aan 4 ontbreekt.
    assert 'value="2"' in web.get(f"{base}/groups/new").text
    assert web.post(f"{base}/groups/new", {"quantity": "3"}).status_code == 422
    r = web.post(f"{base}/groups/new", {"quantity": "2", "dot_code": "0524", "positions": "ra,la"})
    assert r.status_code == 303
    g2 = _groups(web, sid)[1]
    assert g2.positions == "RL,RR"
    # Verwijderen kan zolang er één actieve groep overblijft.
    r = web.post(f"{base}/groups/{g2.id}/delete")
    assert r.status_code == 303
    r = web.post(f"{base}/groups/{g1.id}/delete")
    assert r.status_code == 303
    assert len(_groups(web, sid)) == 1  # laatste groep blijft; melding via flash
    assert "minimaal één actieve groep" in web.c.get(r.headers["location"]).text


def test_banden_vervangen_via_het_formulier(web):
    vid = create_vehicle(web)
    sid = _new_set(web, vid, g1_dot_code="2319")
    (g1,) = _groups(web, sid)
    base = f"/vehicles/{vid}/sets/{sid}/groups/{g1.id}/replace"
    form = web.get(base).text
    assert "Aantal te vervangen banden" in form and 'name="replaced_on"' in form
    r = web.post(base, {"quantity": "1", "dot_code": "1224", "note": "lekke band"})
    assert r.status_code == 303
    groups = _groups(web, sid)
    # Oude groep houdt 3 banden; afgesloten kopie van 1 band; nieuwe actieve groep van 1 band.
    assert sorted((g.quantity, g.dot_code, g.removed_on is None) for g in groups) == [
        (1, "1224", True),
        (1, "2319", False),
        (3, "2319", True),
    ]
    page = web.get(f"/vehicles/{vid}/sets/{sid}").text
    assert "Geschiedenis (1)" in page and "lekke band" in page
    # Meer banden vervangen dan er zijn.
    r = web.post(base, {"quantity": "4", "dot_code": "1224"})
    assert r.status_code == 422 and "niet meer banden vervangen" in r.text
    # Datum in de toekomst.
    r = web.post(base, {"quantity": "1", "replaced_on": "2999-01-01"})
    assert r.status_code == 422


def test_groepsroutes_van_een_ander_voertuig_geven_404(web):
    a = create_vehicle(web)
    b = create_vehicle(web, name="Tweede")
    sid = _new_set(web, a)
    (g,) = _groups(web, sid)
    for url in (
        f"/vehicles/{b}/sets/{sid}",
        f"/vehicles/{b}/sets/{sid}/groups/{g.id}/edit",
        f"/vehicles/{b}/sets/{sid}/groups/{g.id}/replace",
        f"/vehicles/{b}/sets/{sid}/groups/new",
    ):
        assert web.get(url).status_code == 404, url
    assert web.post(f"/vehicles/{b}/sets/{sid}/groups/{g.id}/delete").status_code == 404


def test_groepsposts_vereisen_csrf(web):
    vid = create_vehicle(web)
    sid = _new_set(web, vid)
    (g,) = _groups(web, sid)
    base = f"/vehicles/{vid}/sets/{sid}"
    for url in (
        f"{base}/groups/new",
        f"{base}/groups/{g.id}/edit",
        f"{base}/groups/{g.id}/delete",
        f"{base}/groups/{g.id}/replace",
    ):
        assert web.c.post(url, data={"quantity": "1"}, follow_redirects=False).status_code == 403
    assert len(_groups(web, sid)) == 1


def test_3pmsf_alleen_bij_winter_en_vierseizoenen(web):
    vid = create_vehicle(web)
    # Nieuw-formulier: de checkbox is er (CSS verbergt hem bij zomerbanden), met uitleg en icoon.
    html = web.get(f"/vehicles/{vid}/sets/new").text
    assert 'name="g1_has_3pmsf"' in html and "only-winter" in html
    assert "3PMSF-symbool (bergtop met sneeuwvlok) op de band" in html
    assert "het oude M+S-merk alleen is in o.a. Duitsland en Oostenrijk niet meer genoeg" in html
    assert 'class="icon icon-3pmsf"' in html
    css = web.c.get("/static/app.css").text
    assert ':has(select[name="type"] option[value="summer"]:checked) .only-winter' in css

    # Zomer: de waarde wordt genegeerd en nooit opgeslagen.
    sid = _new_set(web, vid, type="summer", g1_has_3pmsf="1")
    assert _groups(web, sid)[0].has_3pmsf is None
    base = f"/vehicles/{vid}/sets/{sid}"
    (g,) = _groups(web, sid)
    assert "has_3pmsf" not in web.get(f"{base}/groups/{g.id}/edit").text
    assert "icon-3pmsf" not in web.get(base).text
    assert "3PMSF" not in web.get(base).text.split("<main", 1)[1]

    # Winter en vierseizoenen: opslaan en tonen.
    for kind in ("winter", "all_season"):
        sid = _new_set(web, vid, type=kind, g1_has_3pmsf="1")
        (g,) = _groups(web, sid)
        assert g.has_3pmsf is True
        base = f"/vehicles/{vid}/sets/{sid}"
        assert 'name="has_3pmsf"' in web.get(f"{base}/groups/{g.id}/edit").text
        assert "Alle banden hebben het 3PMSF-symbool" in web.get(base).text
    sid = _new_set(web, vid, type="winter")  # symbool niet aangevinkt
    assert _groups(web, sid)[0].has_3pmsf is False
    assert (
        "Niet alle banden hebben het 3PMSF-symbool" in web.get(f"/vehicles/{vid}/sets/{sid}").text
    )
    # Wijzigen via het groepsformulier.
    (g,) = _groups(web, sid)
    base = f"/vehicles/{vid}/sets/{sid}"
    web.post(f"{base}/groups/{g.id}/edit", {"quantity": "4", "has_3pmsf": "1"})
    assert _groups(web, sid)[0].has_3pmsf is True


def test_3pmsf_icoon_in_overzicht_en_voertuigpagina(web):
    vid = create_vehicle(web)
    _new_set(web, vid, status="mounted", g1_has_3pmsf="1")
    for url in ("/", f"/vehicles/{vid}"):
        page = web.get(url).text
        assert "icon-3pmsf" in page and "Alle banden hebben het 3PMSF-symbool" in page, url
    # Eén groep zonder symbool: geen icoon meer.
    other = create_vehicle(web, name="Zonder")
    _new_set(web, other, status="mounted", g1_quantity="2", g1_has_3pmsf="1", g2_quantity="2")
    assert web.get("/").text.count("icon-3pmsf") == 1  # alleen het eerste voertuig


def test_icoon_staat_in_de_macro():
    macros = (WEB / "templates" / "_macros.html").read_text(encoding="utf-8")
    assert "name == '3pmsf'" in macros
