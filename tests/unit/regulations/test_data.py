from __future__ import annotations

import json
import re
from datetime import date
from importlib import resources

import pytest
from pydantic import ValidationError

from wisselweer.regulations.loader import load_country_rules, load_disclaimer
from wisselweer.regulations.models import CountryRule, RuleType

RULES = load_country_rules()
RAW = (
    resources.files("wisselweer.i18n")
    .joinpath("regulations", "winter_tires.json")
    .read_text(encoding="utf-8")
)
MONEY = re.compile(r"€|\bEUR\b|\bCHF\b|\bCZK\b|\bSEK\b|\bDKK\b|boete", re.IGNORECASE)
NOW_PHRASES = re.compile(r"nu verplicht|geldt nu|geldt op dit moment|is nu van kracht", re.I)


def _minimal(**kw):
    base = {
        "code": "BE",
        "name_nl": "België",
        "rule_types": ["none"],
        "tires_nl": "x",
        "sources": [{"title": "t", "url": "https://example.invalid/"}],
        "checked_on": "2026-11-01",
        "confidence": "high",
    }
    return base | kw


def test_first_eight_countries_present():
    assert [c.code for c in RULES] == ["DE", "AT", "FR", "CH", "IT", "BE", "LU", "CZ"]


@pytest.mark.parametrize("rule", RULES, ids=lambda r: r.code)
def test_every_country_has_sources_and_date(rule):
    assert rule.sources and all(s.url.startswith("https://") for s in rule.sources)
    assert rule.checked_on == date(2026, 11, 1)


@pytest.mark.parametrize("rule", RULES, ids=lambda r: r.code)
def test_situational_iff_locations(rule):
    assert rule.is_situational == bool(rule.reference_locations)
    if rule.is_situational:
        assert 2 <= len(rule.reference_locations) <= 6


def test_no_fine_amounts_anywhere():
    assert MONEY.search(RAW) is None


def test_no_text_claims_duty_applies_now():
    assert NOW_PHRASES.search(RAW) is None


def test_uncertain_country_is_marked():
    by = {c.code: c for c in RULES}
    assert by["FR"].confidence != "high" and "Onzeker" in (by["FR"].notes_nl or "")


def test_disclaimer_says_no_legal_advice():
    assert "geen juridisch advies" in load_disclaimer()


def test_coordinates_max_four_decimals():
    for r in json.loads(RAW)["countries"]:
        for loc in r["reference_locations"]:
            for k in ("latitude", "longitude"):
                assert round(loc[k], 4) == loc[k]


def test_model_validation_rules():
    CountryRule.model_validate(_minimal())
    with pytest.raises(ValidationError):  # http niet toegestaan
        CountryRule.model_validate(_minimal(sources=[{"title": "t", "url": "http://x.nl/"}]))
    with pytest.raises(ValidationError):  # geen bronnen
        CountryRule.model_validate(_minimal(sources=[]))
    with pytest.raises(ValidationError):  # extra veld
        CountryRule.model_validate(_minimal(fine=1))
    with pytest.raises(ValidationError):  # lege rule_types
        CountryRule.model_validate(_minimal(rule_types=[]))
    with pytest.raises(ValidationError):  # landcode
        CountryRule.model_validate(_minimal(code="Belgie"))
    locs = [
        {"name": "A", "latitude": 50.0, "longitude": 6.0},
        {"name": "B", "latitude": 50.5, "longitude": 6.5},
    ]
    with pytest.raises(ValidationError):  # situationeel zonder locaties
        CountryRule.model_validate(_minimal(rule_types=["situational"]))
    with pytest.raises(ValidationError):  # locaties zonder situationeel
        CountryRule.model_validate(_minimal(reference_locations=locs))
    with pytest.raises(ValidationError):  # te veel decimalen
        bad = [{**locs[0], "latitude": 50.12345}, locs[1]]
        CountryRule.model_validate(_minimal(rule_types=["situational"], reference_locations=bad))
    ok = CountryRule.model_validate(_minimal(rule_types=["situational"], reference_locations=locs))
    assert RuleType.SITUATIONAL in ok.rule_types


def test_loader_is_cached():
    assert load_country_rules() == load_country_rules()
