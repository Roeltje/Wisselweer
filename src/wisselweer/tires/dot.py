"""DOT-code van een band: productieweek en -jaar (de laatste vier cijfers, WWJJ) en leeftijd.

De code is vrije invoer ("DOT 4KXH 123 2319", "2319"). Alleen de laatste vier cijfers tellen mee.
Ongeldige codes geven `None` in plaats van een fout: een band zonder bruikbare code heeft gewoon
geen leeftijd.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

# De laatste vier cijfers; erachter mag alleen tekst zonder cijfers staan (spatie, punt, letter).
_TAIL = re.compile(r"(\d{4})\D*$")
# Codes uit de toekomst (typefouten) tellen niet; een paar weken speling voor vooruit geleverde banden.
_FUTURE_SLACK_DAYS = 31
DAYS_PER_YEAR = 365.25


def production_date(code: str | None, today: date | None = None) -> date | None:
    """Maandag van de productieweek, of `None` als de code niet te lezen is.

    Week 01-53, jaar 20JJ (codes van vóór 2000 hebben drie cijfers en worden niet herkend).
    Week 53 in een jaar met 52 ISO-weken valt op de maandag van de week erna; dat scheelt
    hooguit enkele dagen.
    """
    if not code:
        return None
    match = _TAIL.search(code.strip())
    if match is None:
        return None
    digits = match.group(1)
    week, year = int(digits[:2]), 2000 + int(digits[2:])
    if not 1 <= week <= 53:
        return None
    produced = date.fromisocalendar(year, 1, 1) + timedelta(weeks=week - 1)
    today = today or date.today()
    if produced > today + timedelta(days=_FUTURE_SLACK_DAYS):
        return None
    return produced


def age_years(produced: date | None, on: date | None = None) -> float | None:
    """Leeftijd in jaren met één decimaal (nooit negatief)."""
    if produced is None:
        return None
    on = on or date.today()
    return round(max((on - produced).days, 0) / DAYS_PER_YEAR, 1)


def dot_age_years(code: str | None, on: date | None = None) -> float | None:
    return age_years(production_date(code, on), on)
