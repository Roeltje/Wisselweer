"""Laadt de gebundelde regelsdata (package data, via importlib.resources)."""

from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources

from wisselweer.regulations.models import CountryRule, RulesFile

_RESOURCE = ("regulations", "winter_tires.json")


@lru_cache(maxsize=1)
def _load() -> RulesFile:
    node = resources.files("wisselweer.i18n")
    for part in _RESOURCE:
        node = node.joinpath(part)
    return RulesFile.model_validate(json.loads(node.read_text(encoding="utf-8")))


def load_country_rules() -> list[CountryRule]:
    return list(_load().countries)


def load_disclaimer() -> str:
    return _load().disclaimer_nl
