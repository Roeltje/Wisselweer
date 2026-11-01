"""Merk- en typesuggesties in de bandenformulieren."""

from __future__ import annotations

from tests.integration.web.conftest import create_vehicle
from tests.integration.web.test_pages import INLINE
from tests.integration.web.test_tire_groups_web import _groups, _new_set
from wisselweer.api.deps import ensure_db
from wisselweer.storage.orm import TireSet


def test_bandenpaginas_hebben_geen_inline_script_of_stijl_en_escapen_invoer(web):
    vid = create_vehicle(web)
    evil = '"><script>alert(1)</script>'
    sid = _new_set(web, vid, brand=evil, model=evil, g1_dot_code='"><script>1', g1_has_3pmsf="1")
    (g,) = _groups(web, sid)
    base = f"/vehicles/{vid}/sets/{sid}"
    urls = [
        f"/vehicles/{vid}/sets/new",
        f"/vehicles/{vid}/sets/{sid}/edit",
        base,
        f"{base}/groups/new",
        f"{base}/groups/{g.id}/edit",
        f"{base}/groups/{g.id}/replace",
        f"/vehicles/{vid}",
        "/",
    ]
    for url in urls:
        body = web.get(url).text
        assert evil not in body, url
        for rx in INLINE:
            assert not rx.search(body), (url, rx.pattern)
    assert "&lt;script&gt;" in web.get(base).text or "&#34;&gt;&lt;script&gt;" in web.get(base).text


def test_merk_en_typesuggesties_in_de_formulieren(web):
    vid = create_vehicle(web)
    html = web.get(f"/vehicles/{vid}/sets/new").text
    # Merkenlijst (alle 28) en een typelijst voor het gekozen seizoen; vrije invoer blijft kunnen.
    brands = html.split('<datalist id="dl-brands">', 1)[1].split("</datalist>", 1)[0]
    assert brands.count("<option") == 28
    assert '<option value="Michelin">' in brands and '<option value="Yokohama">' in brands
    assert 'list="dl-brands"' in html and 'list="dl-models"' in html
    assert '<option value="Primacy 4+">' in html  # zomer is de standaard
    assert '<option value="Alpin 6">' not in html
    assert "data-catalog='" in html and '"Michelin"' in html
    assert 'placeholder="205/55 R16 91H"' in html
    assert "data-msg-size-odd" in html
    assert 'name="g2_brand"' in html and html.count('list="dl-brands"') >= 4
    # Na een fout: de lijst volgt het gekozen seizoen.
    r = web.post(f"/vehicles/{vid}/sets/new", {"type": "winter", "g1_quantity": "9"})
    assert r.status_code == 422 and '<option value="Alpin 6">' in r.text
    # Vrije invoer wordt gewoon opgeslagen.
    sid = _new_set(web, vid, brand="Eigen Merk", model="Onbekend Type", size="rare maat")
    with ensure_db(web.c.app)() as s:
        ts = s.get(TireSet, sid)
        assert (ts.brand, ts.model, ts.size) == ("Eigen Merk", "Onbekend Type", "rare maat")
    # Ook op de bewerk- en groepsformulieren.
    assert 'list="dl-brands"' in web.get(f"/vehicles/{vid}/sets/{sid}/edit").text
    (g,) = _groups(web, sid)
    assert 'list="dl-models"' in web.get(f"/vehicles/{vid}/sets/{sid}/groups/{g.id}/edit").text
