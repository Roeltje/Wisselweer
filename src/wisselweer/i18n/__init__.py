"""Vertalingen: `t(sleutel, locale, **params)` met een fallback-keten per locale.

`nl-NL` = `core.messages.DEFAULT_NL` (engine-teksten, blijft de bron in `core`) aangevuld met
de UI-teksten uit `locales/nl-NL.json`. Ontbreekt een sleutel in een locale, dan volgt de
fallback-keten (nl-BE -> nl-NL; en/de-DE -> nl-NL); ontbreekt hij overal, dan wordt de
sleutel zelf teruggegeven.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from functools import cache
from pathlib import Path
from typing import Any

from wisselweer.core.messages import DEFAULT_NL

DEFAULT_LOCALE = "nl-NL"
SUPPORTED_LOCALES = ("nl-NL", "nl-BE", "en", "de-DE")
FALLBACKS: dict[str, tuple[str, ...]] = {
    "nl-NL": (),
    "nl-BE": ("nl-NL",),
    "en": ("nl-NL",),
    "de-DE": ("nl-NL",),
}
LOCALES_DIR = Path(__file__).parent / "locales"

_WEEKDAYS = {
    "nl": ("ma", "di", "wo", "do", "vr", "za", "zo"),
    "en": ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"),
    "de": ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"),
}
_MONTHS = {
    "nl": ("jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt", "nov", "dec"),
    "en": ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"),
    "de": ("Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"),
}


class _SafeDict(dict[str, object]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


@cache
def _catalog(locale: str) -> dict[str, str]:
    path = LOCALES_DIR / f"{locale}.json"
    data: dict[str, str] = {}
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
    if locale == DEFAULT_LOCALE:
        return {**DEFAULT_NL, **data}
    return data


def normalize_locale(locale: str | None) -> str:
    return locale if locale in SUPPORTED_LOCALES else DEFAULT_LOCALE


def chain(locale: str) -> tuple[str, ...]:
    locale = normalize_locale(locale)
    return (locale, *FALLBACKS[locale])


def has_key(key: str, locale: str = DEFAULT_LOCALE) -> bool:
    return any(key in _catalog(loc) for loc in chain(locale))


def t(key: str, locale: str = DEFAULT_LOCALE, **params: Any) -> str:
    for loc in chain(locale):
        template = _catalog(loc).get(key)
        if template is not None:
            break
    else:
        return key
    if not params:
        return template
    try:
        return template.format_map(_SafeDict(params))
    except (ValueError, IndexError, AttributeError, KeyError):
        return template


def format_date(value: date | datetime | str | None, locale: str = DEFAULT_LOCALE) -> str:
    """Korte datum, NL: 'di 4 nov' (en: 'Tue 4 Nov', de: 'Di 4. Nov')."""
    if value is None or value == "":
        return ""
    if isinstance(value, str):
        try:
            value = date.fromisoformat(value[:10])
        except ValueError:
            return value
    if isinstance(value, datetime):
        value = value.date()
    lang = normalize_locale(locale)[:2]
    wd, mo = _WEEKDAYS[lang][value.weekday()], _MONTHS[lang][value.month - 1]
    dot = "." if lang == "de" else ""
    return f"{wd} {value.day}{dot} {mo}"


def format_datetime(value: datetime | None, locale: str = DEFAULT_LOCALE) -> str:
    if value is None:
        return ""
    return f"{format_date(value, locale)} {value:%H:%M}"
