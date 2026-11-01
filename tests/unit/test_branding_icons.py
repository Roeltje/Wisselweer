"""Zelfgetekende iconen: 3PMSF en M+S (voor de app en voor hergebruik op de website)."""

from __future__ import annotations

import re
from pathlib import Path
from xml.etree import ElementTree

import pytest

ROOT = Path(__file__).resolve().parents[2]
ICONS = ROOT / "branding" / "icons"
MACROS = ROOT / "src" / "wisselweer" / "web" / "templates" / "_macros.html"
NS = "{http://www.w3.org/2000/svg}"


@pytest.mark.parametrize("name", ["3pmsf.svg", "m-s.svg"])
def test_standalone_icoon_is_een_vaste_kleur_64x64_zonder_externe_bronnen(name):
    raw = (ICONS / name).read_text(encoding="utf-8")
    root = ElementTree.fromstring(raw)
    assert root.tag == f"{NS}svg"
    assert root.get("viewBox") == "0 0 64 64"
    assert root.get("stroke") == "#0A3540" and root.get("fill") == "none"
    assert "currentColor" not in raw
    # Geen tekst, lettertypen, afbeeldingen, scripts of verwijzingen naar buiten.
    for forbidden in ("<text", "font", "<image", "<script", "<style", "href", "url(", "http"):
        assert forbidden not in raw.replace("http://www.w3.org/2000/svg", ""), forbidden
    assert root.findall(f".//{NS}path"), "tekening bestaat uit paden"
    colors = set(re.findall(r"#[0-9A-Fa-f]{3,8}\b", raw))
    assert colors == {"#0A3540"}


def test_m_s_zit_in_een_afgerond_kader():
    root = ElementTree.fromstring((ICONS / "m-s.svg").read_text(encoding="utf-8"))
    rect = root.find(f"{NS}rect")
    assert rect is not None and float(rect.get("rx")) > 0


def test_3pmsf_heeft_drie_toppen_en_een_sneeuwvlok():
    root = ElementTree.fromstring((ICONS / "3pmsf.svg").read_text(encoding="utf-8"))
    mountain, flake = root.findall(f"{NS}path")
    # Berg: drie toppen (omhoog-omlaag-omhoog...), gesloten vorm.
    assert mountain.get("d").rstrip().endswith("z")
    # Sneeuwvlok: een verticale lijn en twee diagonalen (drie assen).
    assert len(re.findall(r"[Mm]", flake.get("d"))) == 3


def test_macro_bevat_het_3pmsf_icoon_met_currentcolor():
    macros = MACROS.read_text(encoding="utf-8")
    assert "name == '3pmsf'" in macros
    assert 'stroke="currentColor"' in macros.split("{% macro icon", 1)[1].split("endmacro", 1)[0]
