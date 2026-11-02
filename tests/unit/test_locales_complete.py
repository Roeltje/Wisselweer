"""Regressietest: elke taal bevat dezelfde sleutels en plaatshouders als de bron (nl-NL).

`nl-NL` is `core.messages.DEFAULT_NL` + `locales/nl-NL.json`. `en` en `de-DE` moeten alle sleutels
van de bron bevatten (anders valt de app in die taal terug op Nederlands) en mogen er geen
verzinnen. `nl-BE` bevat bewust alleen afwijkingen: daar mogen geen sleutels staan die nl-NL niet
kent, maar ontbrekende sleutels zijn juist de bedoeling.
"""

from __future__ import annotations

import json
import string

import pytest

from wisselweer.core.messages import DEFAULT_NL
from wisselweer.i18n import LOCALES_DIR, SUPPORTED_LOCALES

FULL_LOCALES = ("en", "de-DE")
# Metasleutel in nl-BE; geen tekst voor de gebruiker.
META_KEYS = {"locale.note"}
# Teksten die in een andere taal toevallig precies hetzelfde zijn ("Kilometerstand" is ook Duits).
SAME_AS_DUTCH = {("de-DE", "change.odometer"), ("de-DE", "odometer.km")}


def _load(locale: str) -> dict[str, str]:
    return json.loads((LOCALES_DIR / f"{locale}.json").read_text(encoding="utf-8"))


def _source() -> dict[str, str]:
    return {**DEFAULT_NL, **_load("nl-NL")}


def _placeholders(text: str) -> list[str]:
    """Namen van de {plaatshouders}, gesorteerd en met herhalingen (zelfde aantal telt mee)."""
    return sorted(name for _, name, _, _ in string.Formatter().parse(text) if name is not None)


def test_source_has_no_duplicate_keys_between_core_and_ui_file():
    # Een sleutel in beide bronnen zou stilletjes door het JSON-bestand overschreven worden.
    assert not (set(DEFAULT_NL) & set(_load("nl-NL")))


@pytest.mark.parametrize("locale", FULL_LOCALES)
def test_full_locale_has_every_source_key(locale):
    missing = sorted(set(_source()) - set(_load(locale)))
    assert not missing, f"{locale} mist {len(missing)} sleutel(s): {missing}"


@pytest.mark.parametrize("locale", FULL_LOCALES)
def test_full_locale_has_no_unknown_keys(locale):
    unknown = sorted(set(_load(locale)) - set(_source()) - META_KEYS)
    assert not unknown, f"{locale} heeft sleutels die nl-NL niet kent: {unknown}"


@pytest.mark.parametrize("locale", FULL_LOCALES)
def test_full_locale_follows_source_order(locale):
    """Dezelfde volgorde als nl-NL.json (daarna de engine-teksten) houdt diffs leesbaar."""
    expected = [*_load("nl-NL"), *(k for k in DEFAULT_NL if k not in _load("nl-NL"))]
    assert list(_load(locale)) == expected


@pytest.mark.parametrize("locale", FULL_LOCALES)
def test_placeholders_match_source(locale):
    source, data = _source(), _load(locale)
    bad = {
        key: (_placeholders(source[key]), _placeholders(text))
        for key, text in data.items()
        if key in source and _placeholders(source[key]) != _placeholders(text)
    }
    assert not bad, f"{locale}: plaatshouders verschillen (bron, vertaling): {bad}"


@pytest.mark.parametrize("locale", FULL_LOCALES)
def test_translations_are_real_text(locale):
    data = _load(locale)
    assert all(isinstance(v, str) and v.strip() for v in data.values()), locale
    # Een vertaling die letterlijk de Nederlandse bronzin is, is bijna zeker vergeten. Echte
    # uitzonderingen (gelijkluidende woorden) staan in SAME_AS_DUTCH.
    same = sorted(
        k
        for k, v in data.items()
        if v == _source().get(k) and len(v) > 12 and (locale, k) not in SAME_AS_DUTCH
    )
    assert not same, f"{locale}: ongewijzigd uit het Nederlands overgenomen: {same}"


def test_dutch_belgium_only_has_overrides():
    source = set(_source())
    unknown = sorted(set(_load("nl-BE")) - source - META_KEYS)
    assert not unknown, f"nl-BE heeft sleutels die nl-NL niet kent: {unknown}"


def test_every_supported_locale_has_a_file():
    for locale in SUPPORTED_LOCALES:
        assert (LOCALES_DIR / f"{locale}.json").is_file(), locale
