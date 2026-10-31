"""Vooruitblik van maximaal 14 dagen voor `advice.json` (optioneel veld `outlook`).

Gebaseerd op de verwachting van EEN referentielocatie (De Bilt, de eerste in de lijst). Die is
dus uitdrukkelijk NIET landelijk representatief. Er worden alleen dagen opgenomen die de
weerbron daadwerkelijk dekt; er wordt nooit iets bijgeschat. Geen extra providerverzoeken.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from wisselweer.core import Forecast, HourlyPoint, PrecipType
from wisselweer.publisher.public_schema import PublicOutlookDay

TZ = ZoneInfo("Europe/Amsterdam")
MAX_DAYS = 14
CONCRETE_DAYS = 7
# Minimaal aantal temperatuurpunten per dag (MET Norway levert op de lange termijn 6-uurlijks).
MIN_POINTS = 4
# Een dag telt alleen mee als de verwachting (vrijwel) het hele etmaal dekt.
END_TOLERANCE = timedelta(hours=3)
# "Nacht" van een dag: 00:00-08:00 en 20:00-24:00 lokale tijd van die kalenderdag.
NIGHT_END = time(8, 0)
NIGHT_START = time(20, 0)
_SNOWY = {PrecipType.SNOW, PrecipType.SLEET}


def _is_night(local: datetime) -> bool:
    return local.time() < NIGHT_END or local.time() >= NIGHT_START


def _snowy(p: HourlyPoint) -> bool:
    return p.precip_type in _SNOWY or (p.snow_cm is not None and p.snow_cm > 0)


def build_outlook(forecast: Forecast, now: datetime) -> list[PublicOutlookDay] | None:
    """Dagelijkse min/max, vorstnacht en sneeuwkans, vanaf de lokale dag van `now`.

    `snow_possible`: ergens op die dag sneeuw/natte sneeuw als neerslagtype of `snow_cm` > 0
    (alleen als de bron die variabelen levert; anders False). Geeft None zonder dekking.
    """
    horizon = forecast.horizon_end()
    if horizon is None:
        return None
    first = now.astimezone(TZ).date()
    by_day: dict = {}
    for p in forecast.hourly:
        by_day.setdefault(p.time.astimezone(TZ).date(), []).append(p)

    days: list[PublicOutlookDay] = []
    for i in range(MAX_DAYS):
        day = first + timedelta(days=i)
        day_end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=TZ)
        if horizon < day_end - END_TOLERANCE:
            break
        points = by_day.get(day, [])
        temps = [(p, p.temperature_c) for p in points if p.temperature_c is not None]
        if len(temps) < MIN_POINTS:
            break
        values = [t for _, t in temps]
        night = [t for p, t in temps if _is_night(p.time.astimezone(TZ))]
        days.append(
            PublicOutlookDay(
                date=day,
                temp_min_c=min(values),
                temp_max_c=max(values),
                frost_night=bool(night) and min(night) <= 0.0,
                snow_possible=any(_snowy(p) for p in points),
                kind="concrete" if i < CONCRETE_DAYS else "trend",
            )
        )
    return days or None
