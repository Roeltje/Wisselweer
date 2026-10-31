"""Configuratie van de adviesengine."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


def _parse_month_day(value: str) -> tuple[int, int]:
    month_s, day_s = value.split("-")
    month, day = int(month_s), int(day_s)
    # 2024 is een schrikkeljaar: valideert ook 02-29.
    from datetime import date

    date(2024, month, day)
    return month, day


class EngineConfig(BaseModel):
    """Alle drempels van de engine.

    LET OP: alle waarden zijn ONGEVALIDEERDE HEURISTIEKEN. Ze zijn niet gekalibreerd
    aan bandenprestaties, ongevallendata of klimatologie en moeten als configureerbare
    startwaarden worden gezien. Zie docs/advice-rules.md.
    """

    # --- Temperatuur ---
    cold_reference_c: float = Field(
        7.0, description="Context (veelgenoemde richtwaarde), géén beslisgrens in de engine."
    )
    cold_day_mean_c: float = Field(
        5.0, description="Dag is 'koud' als rijmoment-temp hieronder ligt."
    )
    cold_streak_days: int = Field(
        3, ge=1, description="Aaneengesloten koude dagen voor winteradvies."
    )
    warm_day_mean_c: float = Field(10.0, description="Dag is 'warm' vanaf deze rijmoment-temp.")
    warm_streak_days: int = Field(
        7, ge=1, description="Aaneengesloten warme dagen voor zomeradvies (langer = asymmetrie)."
    )
    frost_threshold_c: float = Field(0.0, description="Vorst: temperatuur ≤ deze waarde.")
    persistent_frost_days: int = Field(
        3, ge=1, description="Aaneengesloten dagen met vorst die zwaar meetellen voor winteradvies."
    )
    persistent_snow_days: int = Field(
        2,
        ge=1,
        description="Aaneengesloten dagen met sneeuw die zwaar meetellen voor winteradvies.",
    )

    # --- Gladheid ---
    icy_precip_temp_c: float = Field(
        1.0, description="Neerslag (niet-sneeuw) bij ≤ deze temp ⇒ gladheid."
    )
    icy_dewpoint_margin_c: float = Field(
        1.0, description="Bij vorst: dauwpunt ≥ temp − marge duidt op rijp/ijzel."
    )
    icy_humidity_pct: float = Field(
        85.0, description="Minimale luchtvochtigheid voor de dauwpuntregel."
    )
    precip_threshold_mm: float = Field(0.1, description="Per uur ≥ deze waarde telt als neerslag.")

    # --- Seizoensvenster ---
    summer_earliest_month_day: str = Field(
        "03-01", description="Niet eerder naar zomerbanden (MM-DD)."
    )
    winter_earliest_month_day: str = Field(
        "10-01", description="Vanaf hier mag naar winterbanden geadviseerd worden (MM-DD)."
    )

    # --- Horizonnen ---
    short_term_hours: int = Field(72, ge=1, description="Waarschuwingshorizon in uren.")
    concrete_until_day: int = Field(7, ge=1, description="Tot en met deze dag: concrete datum.")
    trend_until_day: int = Field(
        14, ge=1, description="Tot en met deze dag: alleen periode (trend)."
    )
    prepare_days_before: int = Field(
        3, ge=0, description="Voorbereidingsperiode vóór verwachte omslag."
    )

    # --- Datakwaliteit ---
    stale_after_hours: float = Field(
        6.0, description="Forecast ouder dan dit ⇒ FORECAST_STALE-waarschuwing."
    )
    max_forecast_age_hours: float = Field(
        36.0, description="Forecast ouder dan dit ⇒ onbruikbaar (INSUFFICIENT_DATA)."
    )
    min_hours_required: int = Field(
        24, ge=1, description="Minimaal aantal toekomstige uren met temperatuur."
    )
    min_hours_per_day: int = Field(
        8, ge=1, description="Minimaal aantal uren met temperatuur voor een bruikbare dag."
    )

    # --- Stabiliteit ---
    hysteresis_confirmations: int = Field(
        2,
        ge=1,
        description="Opeenvolgende evaluaties nodig voor statuswijziging (waar van toepassing).",
    )

    @field_validator("summer_earliest_month_day", "winter_earliest_month_day")
    @classmethod
    def _check_md(cls, v: str) -> str:
        try:
            _parse_month_day(v)
        except Exception as exc:  # noqa: BLE001
            raise ValueError("verwacht formaat MM-DD") from exc
        return v

    @property
    def summer_earliest(self) -> tuple[int, int]:
        return _parse_month_day(self.summer_earliest_month_day)

    @property
    def winter_earliest(self) -> tuple[int, int]:
        return _parse_month_day(self.winter_earliest_month_day)
