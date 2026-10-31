"""Landelijk advies: de engine draait per referentielocatie; de uitkomsten worden samengevoegd.

LET OP: alle drempels hier (`agreement_ratio`, `min_regions_with_data`, seizoensvensters) en in
de onderliggende `EngineConfig` zijn ONGEVALIDEERDE HEURISTIEKEN en configureerbaar.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Literal, cast
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, field_validator

from wisselweer.core import (
    RULES_VERSION,
    Advice,
    AdviceInput,
    AdviceStatus,
    DrivingProfile,
    TireType,
    WarningCode,
    evaluate,
)
from wisselweer.core.config import EngineConfig, _parse_month_day
from wisselweer.i18n import t
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
    def __init__(self, name: str, advice: Advice | None, provider: str | None = None) -> None:
        self.name = name
        self.advice = advice
        self.provider = provider

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
    def __init__(self, forecast_service: ForecastService, config: NationalConfig | None = None):
        self._forecasts = forecast_service
        self._cfg = config or NationalConfig()

    def compute(self, now: datetime | None = None) -> PublicAdvice:
        cfg = self._cfg
        now = (now or datetime.now(UTC)).astimezone(UTC).replace(microsecond=0)
        season = cfg.season_for(now.astimezone(TZ).date())
        mounted = TireType.SUMMER if season == "winter" else TireType.WINTER
        results = [self._region(loc, mounted, now) for loc in cfg.locations]
        status, agreeing = self._aggregate(results)
        recommended_date, period = self._dates(status, agreeing)

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
            generated_at=now,
            stale_after=now + timedelta(hours=cfg.stale_hours),
            source=self._source(results),
            rules_version=RULES_VERSION,
        )

    # ------------------------------------------------------------------ intern

    def _region(self, loc: ReferenceLocation, mounted: TireType, now: datetime) -> _RegionResult:
        try:
            forecast = self._forecasts.get_forecast(loc.latitude, loc.longitude)
        except Exception as exc:  # noqa: BLE001 - elke providerfout ⇒ regio zonder data
            log.warning("region_forecast_failed region=%s type=%s", loc.name, type(exc).__name__)
            return _RegionResult(loc.name, None)
        advice = evaluate(
            AdviceInput(
                forecast=forecast,
                mounted=mounted,
                profile=DrivingProfile.daytime(),
                now=now,
                lead_time_days=0,
                config=self._cfg.engine,
            )
        )
        return _RegionResult(loc.name, advice, forecast.provider)

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
