"""Merk- en typecatalogus: bestand, inhoud en hulpfuncties."""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import date

import pytest

from wisselweer.tires import catalog

BRANDS = [
    "Barum",
    "BFGoodrich",
    "Bridgestone",
    "Continental",
    "Dunlop",
    "Falken",
    "Firestone",
    "Fulda",
    "General Tire",
    "Goodyear",
    "Hankook",
    "Kleber",
    "Kormoran",
    "Kumho",
    "Laufenn",
    "Linglong",
    "Maxxis",
    "Michelin",
    "Nankang",
    "Nexen",
    "Nokian",
    "Pirelli",
    "Sava",
    "Semperit",
    "Toyo",
    "Uniroyal",
    "Vredestein",
    "Yokohama",
]


def test_catalogus_bevat_precies_de_28_merken_alfabetisch():
    names = catalog.brand_names()
    assert names == BRANDS
    assert len(names) == 28
    assert names == sorted(names, key=str.casefold)


def test_metadata_en_vorm():
    data = catalog.load_catalog()
    date.fromisoformat(data["checked_on"])
    assert "geen volledige lijst" in data["note"]
    for brand in data["brands"]:
        assert set(brand) == {"name", "summer", "all_season", "winter"}
        for season in catalog.SEASONS:
            models = brand[season]
            assert len(models) <= 4, (brand["name"], season)  # 0-4 typen per seizoen
            assert len(set(models)) == len(models)
            assert all(isinstance(m, str) and m == m.strip() and m for m in models)
    # Het bestand is gewoon JSON met de verwachte sleutels bovenin.
    raw = json.loads(catalog.CATALOG_PATH.read_text(encoding="utf-8"))
    assert list(raw)[:2] == ["checked_on", "note"]


def test_modellen_per_merk_en_seizoen():
    assert catalog.models_for("winter", "Michelin") == ["Alpin 6", "Pilot Alpin 5"]
    assert catalog.models_for("winter", "  michelin ") == [
        "Alpin 6",
        "Pilot Alpin 5",
    ]  # hoofdletterloos
    assert "CrossClimate 2" in catalog.models_for("all_season", "Michelin")
    assert catalog.models_for("winter", "Linglong") == []  # bewust leeg gelaten, geen gok


def test_onbekend_merk_geeft_alle_typen_van_het_seizoen():
    everything = catalog.models_for("summer")
    assert catalog.models_for("summer", "Onbekend Merk") == everything
    assert everything == sorted(set(everything), key=str.casefold)
    assert "Primacy 4+" in everything and "Alpin 6" not in everything
    assert catalog.models_for("slicks") == [] and catalog.models_for(None) == []


def test_clientdata_voor_appjs():
    data = catalog.client_data()
    assert list(data) == BRANDS
    assert data["Toyo"]["winter"][0] == "Snowprox S954"


def test_bestand_zit_in_het_pakket_en_wordt_niet_genegeerd():
    """`data/` stond in .gitignore: dan ontbreekt het bestand in git en in de wheel."""
    assert catalog.CATALOG_PATH.parts[-3:] == ("wisselweer", "data", "tire_catalog.json")
    git = shutil.which("git")
    if git is None:
        pytest.skip("git niet beschikbaar")
    repo = catalog.CATALOG_PATH.parents[3]
    if not (repo / ".git").exists():
        pytest.skip("geen git-checkout")
    result = subprocess.run(
        [git, "check-ignore", "-q", str(catalog.CATALOG_PATH)], cwd=repo, check=False
    )
    assert result.returncode == 1, "tire_catalog.json wordt door .gitignore genegeerd"
