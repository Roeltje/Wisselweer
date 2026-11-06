"""Landelijk advies: de engine draait per referentielocatie; de uitkomsten worden samengevoegd.

LET OP: alle drempels hier (`agreement_ratio`, `min_regions_with_data`, seizoensvensters) en in
de onderliggende `EngineConfig` zijn ONGEVALIDEERDE HEURISTIEKEN en configureerbaar.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, field_validator

from wisselweer.core import (
    RULES_VERSION,
    Advice,
    AdviceInput,
    AdviceStatus,
    DriveSlot,
    DrivingProfile,
    Forecast,
    TireType,
    WarningCode,
    evaluate,
)
from wisselweer.core.config import EngineConfig, _parse_month_day
from wisselweer.i18n import t
from wisselweer.publisher.national_stability import (
    NationalHold,
    NationalState,
    dampen_national_status,
    load_state,
    save_state,
)
from wisselweer.publisher.outlook import build_outlook
from wisselweer.publisher.public_schema import (
    PublicAdvice,
    PublicPeriod,
    PublicRegion,
    PublicSource,
    PublicStatus,
    RegionStatus,
)

if TYPE_CHECKING:
    from wisselweer.weather.service import ForecastService

log = logging.getLogger("wisselweer.publisher")

TZ = ZoneInfo("Europe/Amsterdam")
_FORECAST_WARNINGS = {WarningCode.FORECAST_UNAVAILABLE, WarningCode.FORECAST_STALE}


def national_profile() -> DrivingProfile:
    """Landelijk rijprofiel: werkdagen (ma–vr) 07:00–09:00 en 16:00–19:00 (ochtend- en avondspits),
    za/zo 10:00–18:00.

    Bron van het idee: CBS Onderweg in Nederland (ODiN), waarin het autoverkeer pieken kent in de
    ochtend- en avondspits op werkdagen en een drukke zaterdagmiddag. De exacte grenzen zijn een
    ONGEVALIDEERDE HEURISTIEK (afgerond op de spitsen, niet gefit op ODiN-microdata).
    """
    slots = [
        DriveSlot(weekday=d, start=time(*s), end=time(*e))
        for d in range(5)
        for s, e in (((7,), (9,)), ((16,), (19,)))
    ]
    slots += [DriveSlot(weekday=d, start=time(10), end=time(18)) for d in (5, 6)]
    return DrivingProfile.custom(slots)


class ReferenceLocation(BaseModel):
    """Publieke referentieplaats (geen gebruikerslocatie)."""

    name: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


# Gekozen voor geografische spreiding: kust (Den Helder, Vlissingen), binnenland (De Bilt, Arnhem),
# noord (Groningen), oost (Twente) en zuid (Maastricht). Configureerbaar via de instellingen.
DEFAULT_LOCATIONS: tuple[ReferenceLocation, ...] = (
    ReferenceLocation(name="De Bilt", latitude=52.1017, longitude=5.1780),
    ReferenceLocation(name="Groningen", latitude=53.2194, longitude=6.5665),
    ReferenceLocation(name="Den Helder", latitude=52.9533, longitude=4.7600),
    ReferenceLocation(name="Vlissingen", latitude=51.4423, longitude=3.5736),
    ReferenceLocation(name="Maastricht", latitude=50.8514, longitude=5.6910),
    ReferenceLocation(name="Twente (Enschede)", latitude=52.2215, longitude=6.8937),
    ReferenceLocation(name="Arnhem", latitude=51.9851, longitude=5.8987),
)


class NationalConfig(BaseModel):
    locations: list[ReferenceLocation] = Field(default_factory=lambda: list(DEFAULT_LOCATIONS))
    # Vanaf deze datum (MM-DD) is de vraag "winterbanden" (zomerbanden gemonteerd)...
    winter_question_from: str = "08-01"
    # ...en vanaf deze datum de vraag "zomerbanden" (winterbanden gemonteerd).
    summer_question_from: str = "02-01"
    agreement_ratio: float = Field(0.75, gt=0.5, le=1.0)
    min_regions_with_data: int | None = Field(None, ge=1)
    stale_hours: float = Field(18.0, gt=0)
    engine: EngineConfig = Field(default_factory=EngineConfig)

    @field_validator("winter_question_from", "summer_question_from")
    @classmethod
    def _md(cls, v: str) -> str:
        try:
            _parse_month_day(v)
        except Exception as exc:  # noqa: BLE001
            raise ValueError("verwacht formaat MM-DD") from exc
        return v

    def min_regions(self) -> int:
        return self.min_regions_with_data or (len(self.locations) // 2 + 1)

    def season_for(self, day: date) -> Literal["winter", "summer"]:
        md = (day.month, day.day)
        winter_from = _parse_month_day(self.winter_question_from)
        summer_from = _parse_month_day(self.summer_question_from)
        if summer_from < winter_from:
            return "summer" if summer_from <= md < winter_from else "winter"
        return "winter" if winter_from <= md < summer_from else "summer"


class _RegionResult:
    def __init__(
        self,
        name: str,
        advice: Advice | None,
        provider: str | None = None,
        forecast: Forecast | None = None,
    ) -> None:
        self.name = name
        self.advice = advice
        self.provider = provider
        self.forecast = forecast

    @property
    def has_data(self) -> bool:
        return self.advice is not None and self.advice.status != AdviceStatus.INSUFFICIENT_DATA

    @property
    def status(self) -> RegionStatus:
        if not self.has_data:
            return "INSUFFICIENT_DATA"
        assert self.advice is not None
        return cast(RegionStatus, self.advice.status.value.upper())


class NationalAdviceService:
    def __init__(
        self,
        forecast_service: ForecastService,
        config: NationalConfig | None = None,
        state_path: Path | None = None,
        persist: bool = True,
    ):
        """`state_path`: statebestand voor de demping tussen berekeningen. Alleen de publicatie
        schrijft (`persist=True`); een API-aanroep leest alleen (`persist=False`)."""
        self._forecasts = forecast_service
        self._cfg = config or NationalConfig()
        self._state_path = state_path
        self._persist = persist

    def compute(self, now: datetime | None = None) -> PublicAdvice:
        cfg = self._cfg
        now = (now or datetime.now(UTC)).astimezone(UTC).replace(microsecond=0)
        season = cfg.season_for(now.astimezone(TZ).date())
        mounted = TireType.SUMMER if season == "winter" else TireType.WINTER
        state = load_state(self._state_path, now, season)
        previous_regions = state.regions if state else {}
        results = [
            self._region(loc, mounted, now, previous_regions.get(loc.name)) for loc in cfg.locations
        ]
        raw_status, agreeing = self._aggregate(results)
        recommended_date, period = self._dates(raw_status, agreeing)
        decision = dampen_national_status(
            raw_status,
            season,
            state.national if state else None,
            cfg.engine.hysteresis_confirmations,
        )
        status = decision.status
        if decision.held:
            assert state is not None and state.national is not None
            recommended_date = state.national.recommended_date
            period = state.national.recommended_period
            agreeing = []

        horizons = [
            r.advice.horizon_until
            for r in results
            if r.has_data and r.advice and r.advice.horizon_until
        ]
        local_warning = any(
            w.code not in _FORECAST_WARNINGS for r in results if r.advice for w in r.advice.warnings
        )
        summary = t(
            f"public.summary.{status}"
            if status in ("REGIONAL_DIFFERENCES", "INSUFFICIENT_DATA")
            else f"public.summary.{status}.{season}"
        )
        if local_warning and status != "INSUFFICIENT_DATA":
            summary = f"{summary} {t('public.warning_note')}"

        if self._persist and self._state_path is not None:
            save_state(
                self._state_path,
                NationalState(
                    regions={r.name: r.advice for r in results if r.advice is not None},
                    national=NationalHold(
                        season=season,
                        status=status,
                        raw_status=decision.raw_status,
                        streak=decision.streak,
                        recommended_date=recommended_date,
                        recommended_period=period,
                    ),
                    generated_at=now,
                ),
            )

        return PublicAdvice(
            next_season=season,
            heading=t(f"public.heading.{season}"),
            status=status,
            status_label=t(f"public.status_label.{status}"),
            summary=summary,
            recommended_date=recommended_date,
            recommended_period=period,
            regional_variation=len({r.status for r in results}) > 1,
            regions=[PublicRegion(name=r.name, status=r.status) for r in results],
            forecast_until=min(horizons) if horizons and status != "INSUFFICIENT_DATA" else None,
            outlook=self._outlook(results, now),
            generated_at=now,
            stale_after=now + timedelta(hours=cfg.stale_hours),
            source=self._source(results),
            rules_version=RULES_VERSION,
        )

    # ------------------------------------------------------------------ intern

    def _region(
        self,
        loc: ReferenceLocation,
        mounted: TireType,
        now: datetime,
        previous: Advice | None = None,
    ) -> _RegionResult:
        try:
            forecast = self._forecasts.get_forecast(loc.latitude, loc.longitude)
        except Exception as exc:  # noqa: BLE001 - elke providerfout ⇒ regio zonder data
            log.warning("region_forecast_failed region=%s type=%s", loc.name, type(exc).__name__)
            return _RegionResult(loc.name, None)
        advice = evaluate(
            AdviceInput(
                forecast=forecast,
                mounted=mounted,
                profile=national_profile(),
                now=now,
                lead_time_days=0,
                previous=previous,
                config=self._cfg.engine,
            )
        )
        return _RegionResult(loc.name, advice, forecast.provider, forecast)

    @staticmethod
    def _outlook(results: list[_RegionResult], now: datetime):
        """Vooruitblik uit de eerste referentielocatie (De Bilt); alleen indicatief."""
        ref = results[0] if results else None
        if ref is None or ref.forecast is None:
            return None
        return build_outlook(ref.forecast, now, national_profile())

    def _aggregate(self, results: list[_RegionResult]) -> tuple[PublicStatus, list[_RegionResult]]:
        with_data = [r for r in results if r.has_data]
        if len(with_data) < self._cfg.min_regions():
            return "INSUFFICIENT_DATA", []
        top, count = Counter(r.status for r in with_data).most_common(1)[0]
        if count >= self._cfg.agreement_ratio * len(with_data) - 1e-9:
            return cast(PublicStatus, top), [r for r in with_data if r.status == top]
        return "REGIONAL_DIFFERENCES", []

    @staticmethod
    def _dates(
        status: PublicStatus, agreeing: list[_RegionResult]
    ) -> tuple[date | None, PublicPeriod | None]:
        if not agreeing:
            return None, None
        dates: list[date] = []
        points: list[date] = []
        for r in agreeing:
            assert r.advice is not None
            a = r.advice
            if a.recommended_date is not None:
                dates.append(a.recommended_date)
                points.append(a.recommended_date)
            elif a.recommended_period is not None:
                points.extend(a.recommended_period)
            else:
                return None, None  # niet alle eensgezinde regio's onderbouwen een datum
        if len(dates) == len(agreeing) and len(set(dates)) == 1:
            return dates[0], None
        return None, PublicPeriod(start=min(points), end=max(points))

    def _source(self, results: list[_RegionResult]) -> PublicSource:
        used = next((r.provider for r in results if r.provider), None)
        pid = used or self._forecasts.default_provider
        for info in self._forecasts.provider_infos():
            if info.id == pid:
                return PublicSource(
                    name=info.name, attribution=info.attribution, license_url=info.license_url
                )
        raise ValueError("weerbron onbekend")
