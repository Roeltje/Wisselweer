from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path

from wisselweer.core.messages import DEFAULT_NL
from wisselweer.i18n import LOCALES_DIR, chain, format_date, format_datetime, has_key, t

WEB = Path(__file__).parents[3] / "src" / "wisselweer" / "web"


def test_nl_contains_engine_messages_and_ui_texts():
    assert (
        t("heading.to_winter.change_recommended")
        == DEFAULT_NL["heading.to_winter.change_recommended"]
    )
    assert t("nav.dashboard") == "Overzicht"
    assert t("reason.cold_streak", start="x", days=3, threshold=7).startswith("Vanaf x zijn er 3")


def test_fallback_chain():
    assert chain("nl-BE") == ("nl-BE", "nl-NL")
    assert chain("en") == ("en", "nl-NL")
    assert chain("de-DE") == ("de-DE", "nl-NL")
    assert chain("xx") == ("nl-NL",)
    # nl-BE heeft (bijna) niets eigens: valt terug op nl-NL
    assert t("nav.dashboard", "nl-BE") == "Overzicht"
    # en/de vertaald waar beschikbaar, anders nl-NL
    assert t("nav.dashboard", "en") == "Overview"
    assert t("nav.dashboard", "de-DE") == "Übersicht"
    assert t("advice.question.to_winter", "en") == "When winter tires?"
    assert t("garage.new", "en") == t("garage.new", "nl-NL")  # ontbreekt in en
    assert t("reason.no_forecast", "de-DE") == DEFAULT_NL["reason.no_forecast"]
    # onbekende sleutel => sleutel zelf
    assert t("bestaat.niet", "en") == "bestaat.niet"
    assert not has_key("bestaat.niet")


def test_params_and_missing_params():
    assert t("advice.plan_by", date="di 4 nov") == "Plan een afspraak vóór di 4 nov"
    assert "{date}" in t("advice.plan_by")  # ontbrekende parameter blijft staan, geen crash


def test_dates_dutch():
    assert format_date(date(2025, 11, 4)) == "di 4 nov"
    assert format_date("2025-03-01") == "za 1 mrt"
    assert format_datetime(datetime(2025, 11, 4, 14, 5)) == "di 4 nov 14:05"
    assert format_date(date(2025, 11, 4), "en") == "Tue 4 Nov"
    assert format_date(None) == ""


def test_locale_files_valid_and_core_keys_translated():
    nl = json.loads((LOCALES_DIR / "nl-NL.json").read_text(encoding="utf-8"))
    for loc in ("nl-BE", "en", "de-DE"):
        data = json.loads((LOCALES_DIR / f"{loc}.json").read_text(encoding="utf-8"))
        assert isinstance(data, dict)
        if loc != "nl-BE":
            for key in (
                "nav.dashboard",
                "nav.settings",
                "status.keep_current",
                "status.change_recommended",
                "advice.question.to_winter",
                "advice.question.to_summer",
                "tire.type.winter",
                "heading.to_winter.change_recommended",
                "heading.none.keep_current",
            ):
                assert key in data, (loc, key)
            assert set(data) - {"locale.note"} <= set(nl) | set(DEFAULT_NL), loc


def test_every_key_used_in_ui_exists():
    used: set[str] = set()
    for path in [*WEB.glob("templates/*.html"), WEB / "routes.py", WEB / "views.py"]:
        text = path.read_text(encoding="utf-8")
        used |= set(re.findall(r"""\b(?:t|tr)\(\s*['"]([a-z_.]+[a-z_])['"]""", text))
        used |= set(
            re.findall(r"""(?:Field\(\s*"[a-z_]+",\s*|label=|help=)"([a-z_]+\.[a-z_.]+)"?""", text)
        )
    assert len(used) > 80
    missing = sorted(k for k in used if not has_key(k))
    assert not missing, missing
    # dynamische sleutels
    for key in [
        *(
            f"status.{s}"
            for s in ("keep_current", "prepare_change", "change_recommended", "insufficient_data")
        ),
        *(
            f"appointment.status.{s}"
            for s in ("not_planned", "to_request", "requested", "confirmed", "done", "cancelled")
        ),
        *(f"weekday.{d}" for d in range(7)),
        *(f"weekday.short.{d}" for d in range(7)),
        *(f"tread.{p}" for p in ("FL", "FR", "RL", "RR")),
        *(f"tread.short.{p}" for p in ("FL", "FR", "RL", "RR")),
        *(
            f"warning.label.{w}"
            for w in ("possible_frost", "possible_snow", "possible_icy_conditions")
        ),
        "provider.missing_contact",
        "provider.openmeteo_noncommercial",
        "provider.knmi_forecast_not_available",
        "provider.missing_credentials",
        "odometer.source.manual",
        "odometer.source.tire_change",
        "direction.to_winter",
        "direction.to_summer",
        "method.self",
        "method.garage",
        "tire.status.mounted",
        "tire.status.stored",
        "tire.status.retired",
    ]:
        assert has_key(key), key
