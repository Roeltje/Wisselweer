"""Nederlandse standaardteksten per i18n-sleutel (later naar i18n/locales/nl-NL.json).

Plaatshouders {naam} worden gevuld uit ReasonItem.params. Tijdelijk hier; de engine
zelf gebruikt alleen de sleutels.
"""

from __future__ import annotations

from wisselweer.core.models import AdviceStatus, Direction, heading_key

_HEADINGS = {
    (Direction.TO_WINTER, AdviceStatus.KEEP_CURRENT): "Zomerbanden kunnen er nog op blijven",
    (Direction.TO_WINTER, AdviceStatus.PREPARE_CHANGE): "Bereid de wissel naar winterbanden voor",
    (Direction.TO_WINTER, AdviceStatus.CHANGE_RECOMMENDED): "Tijd voor winterbanden",
    (Direction.TO_SUMMER, AdviceStatus.KEEP_CURRENT): "Winterbanden kunnen er nog op blijven",
    (Direction.TO_SUMMER, AdviceStatus.PREPARE_CHANGE): "Bereid de wissel naar zomerbanden voor",
    (Direction.TO_SUMMER, AdviceStatus.CHANGE_RECOMMENDED): "Tijd voor zomerbanden",
    (Direction.NONE, AdviceStatus.KEEP_CURRENT): "Vierseizoenenbanden: geen wissel nodig",
}

DEFAULT_NL: dict[str, str] = {heading_key(d, s): text for (d, s), text in _HEADINGS.items()} | {
    heading_key(d, AdviceStatus.INSUFFICIENT_DATA): "Nog geen betrouwbaar advies beschikbaar"
    for d in Direction
}

DEFAULT_NL |= {
    # redenen
    "reason.cold_streak": "Vanaf {start} zijn er {days} koude dagen op rij verwacht (onder {threshold} °C).",
    "reason.persistent_frost": "Vanaf {start} wordt aanhoudende vorst verwacht ({days} dagen).",
    "reason.persistent_snow": "Vanaf {start} wordt aanhoudend sneeuw verwacht ({days} dagen).",
    "reason.trend_only": "De omslag ligt verder dan een week vooruit; alleen een periode, geen datum.",
    "reason.no_sustained_cold": "Geen aanhoudende kou in de verwachting.",
    "reason.winter_season_not_open": "Het is buiten het seizoen voor winterbanden.",
    "reason.summer_season_not_open": "Het is nog te vroeg in het jaar voor zomerbanden.",
    "reason.frost_in_horizon": "Er is nog vorst of sneeuw in de verwachting (eerste dag {first_day}).",
    "reason.warm_streak": "Vanaf {start} zijn er {days} warme dagen op rij verwacht (vanaf {threshold} °C).",
    "reason.warm_spell_too_short": "De warme periode is te kort om zomerbanden te rechtvaardigen.",
    "reason.not_warm_enough": "Het wordt nog niet aanhoudend warm genoeg.",
    "reason.drive_window_fallback": "Voor {days} dag(en) zonder rijmoment is het daggemiddelde gebruikt.",
    "reason.drive_window_used": "Temperaturen zijn gewogen naar je rijmomenten.",
    "reason.appointment_urgent": "Plan zo snel mogelijk: de gewenste afspraakdatum is al verstreken.",
    "reason.all_season_warnings_only": "Vierseizoenenbanden: alleen waarschuwingen, geen wisseladvies.",
    "reason.no_mounted_set": "Er is geen gemonteerde bandenset bekend.",
    "reason.no_forecast": "Er is geen weersverwachting beschikbaar.",
    "reason.forecast_too_old": "De weersverwachting is te oud om op te vertrouwen.",
    "reason.insufficient_hours": "De weersverwachting bevat te weinig bruikbare uren.",
    "reason.status_held": "Advies nog niet gewijzigd: wacht op bevestiging ({streak} van {needed}).",
    # onzekerheden
    "uncertainty.beyond_horizon": "De weersverwachting reikt niet ver genoeg om de omslag te bevestigen.",
    "uncertainty.missing_variable": "Niet geleverd door de weerbron: {variable}.",
    "uncertainty.forecast_stale": "De weersverwachting is niet vers; het advies kan veranderen.",
    # waarschuwingen
    "warning.frost": "Vorst mogelijk.",
    "warning.frost.summer_tires": "Vorst mogelijk: let op, je rijdt op zomerbanden.",
    "warning.snow": "Sneeuw mogelijk.",
    "warning.snow.summer_tires": "Sneeuw mogelijk: zomerbanden zijn hier niet geschikt voor.",
    "warning.icy": "Kans op gladheid.",
    "warning.icy.summer_tires": "Kans op gladheid: let op, je rijdt op zomerbanden.",
    "warning.forecast_unavailable": "Geen weersverwachting beschikbaar.",
    "warning.forecast_stale": "De weersverwachting is verouderd.",
}
