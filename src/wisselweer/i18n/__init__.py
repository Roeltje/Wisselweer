"""Vertalingen: `t(sleutel, locale, **params)` met een fallback-keten per locale.

`nl-NL` = `core.messages.DEFAULT_NL` (engine-teksten, blijft de bron in `core`) aangevuld met
de UI-teksten uit `locales/nl-NL.json`. Ontbreekt een sleutel in een locale, dan volgt de
fallback-keten (nl-BE -> nl-NL; en/de-DE -> nl-NL, alleen een vangnet: en en de-DE bevatten alle
sleutels, zie tests); ontbreekt hij overal, dan wordt de sleutel zelf teruggegeven.
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
# Naam van elke taal in die taal zelf (bewust niet vertaald per UI-taal: een gebruiker moet zijn
# eigen taal altijd herkennen). Gebruikt door de taalkiezer in de footer.
LOCALE_NAMES: dict[str, str] = {
    "nl-NL": "Nederlands",
    "nl-BE": "Nederlands (België)",
    "en": "English",
    "de-DE": "Deutsch",
}
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


def negotiate_locale(accept_language: str | None) -> str:
    """Kiest een locale uit een `Accept-Language`-header (met q-waarden).

    `nl-BE` -> nl-BE, andere `nl*` -> nl-NL, `en*` -> en, `de*` -> de-DE; wat we niet kennen wordt
    overgeslagen en zonder treffer volgt de standaardtaal. Foute of absurd lange invoer is veilig.
    """
    if not accept_language:
        return DEFAULT_LOCALE
    candidates: list[tuple[float, int, str]] = []
    for index, part in enumerate(accept_language[:500].split(",")[:20]):
        tag, _, params = part.partition(";")
        tag = tag.strip().lower().replace("_", "-")
        if not tag:
            continue
        quality = 1.0
        for param in params.split(";"):
            name, _, value = param.partition("=")
            if name.strip().lower() == "q":
                try:
                    quality = float(value.strip())
                except ValueError:
                    quality = 0.0
        if quality > 0:
            candidates.append((-min(quality, 1.0), index, tag))
    for _, _, tag in sorted(candidates):
        if tag == "nl-be":
            return "nl-BE"
        primary = tag.split("-", 1)[0]
        if primary == "nl":
            return "nl-NL"
        if primary == "en":
            return "en"
        if primary == "de":
            return "de-DE"
    return DEFAULT_LOCALE


def request_locale(request: Any, *, persist: bool = True) -> str:
    """Taal van een request: expliciete keuze (`?lang=`, bewaard in de sessie) gaat voor, dan de
    taal in de sessie, dan de browsertaal (`Accept-Language`), anders de standaardtaal."""
    lang = request.query_params.get("lang")
    if lang in SUPPORTED_LOCALES:
        if persist:
            request.session["lang"] = lang
        return lang
    stored = request.session.get("lang")
    if stored in SUPPORTED_LOCALES:
        return stored
    return negotiate_locale(request.headers.get("accept-language"))


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


# (decimaalteken, duizendtal-scheiding) per taal
_SEPARATORS = {"nl": (",", "."), "en": (".", ","), "de": (",", ".")}


def format_number(value: float, locale: str = DEFAULT_LOCALE, decimals: int = 0) -> str:
    """Getal met de decimaal- en duizendtalscheiding van de taal (nl/de: 1.234,5; en: 1,234.5)."""
    decimal, group = _SEPARATORS[normalize_locale(locale)[:2]]
    text = f"{value:,.{decimals}f}"
    return text.replace(",", "\0").replace(".", decimal).replace("\0", group)


def format_euro(cents: int | None, locale: str = DEFAULT_LOCALE) -> str:
    """Bedrag in euro (nl: '€ 1.234,50'; en: '€1,234.50'; de: '1.234,50 €')."""
    if cents is None:
        return ""
    amount = format_number(cents / 100, locale, 2)
    lang = normalize_locale(locale)[:2]
    if lang == "de":
        return f"{amount} €"
    return f"€ {amount}" if lang == "nl" else f"€{amount}"


def format_datetime(value: datetime | None, locale: str = DEFAULT_LOCALE) -> str:
    if value is None:
        return ""
    return f"{format_date(value, locale)} {value:%H:%M}"
