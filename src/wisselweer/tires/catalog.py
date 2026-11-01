"""Merk- en typesuggesties voor het bandenformulier (`data/tire_catalog.json`).

Alleen suggesties: vrije invoer blijft altijd mogelijk en er wordt nergens op gevalideerd.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

CATALOG_PATH = Path(__file__).resolve().parent.parent / "data" / "tire_catalog.json"
SEASONS = ("summer", "all_season", "winter")


@cache
def load_catalog() -> dict[str, Any]:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def brand_names() -> list[str]:
    return [b["name"] for b in load_catalog()["brands"]]


def models_for(season: str | None, brand: str | None = None) -> list[str]:
    """Typenamen voor een seizoen (`summer`, `all_season`, `winter`).

    Met een bekend merk de typen van dat merk; anders alle typen van dat seizoen, zonder dubbelen
    en alfabetisch. Onbekend seizoen geeft een lege lijst.
    """
    if season not in SEASONS:
        return []
    wanted = (brand or "").strip().casefold()
    brands = load_catalog()["brands"]
    if wanted:
        for b in brands:
            if b["name"].casefold() == wanted:
                return list(b[season])
    return sorted({m for b in brands for m in b[season]}, key=str.casefold)


def client_data() -> dict[str, dict[str, list[str]]]:
    """Compacte vorm voor app.js: `{merk: {seizoen: [typen]}}`."""
    return {b["name"]: {s: b[s] for s in SEASONS} for b in load_catalog()["brands"]}
