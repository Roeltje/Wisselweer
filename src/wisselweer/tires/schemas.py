"""Pydantic-schema's voor banden, metingen en wissels."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from wisselweer.core.models import TireType
from wisselweer.storage.enums import ChangeMethod, OdometerSource, Position, TireStatus

MAX_TIRES = 4
_POSITION_ORDER = ("FL", "FR", "RL", "RR")
# Nederlandse afkortingen (links/rechts voor/achter) zijn ook toegestaan.
_POSITION_ALIASES = {"LV": "FL", "RV": "FR", "LA": "RL", "RA": "RR"}


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


class TireGroupBase(BaseModel):
    """Velden die een groep banden beschrijven (gedeeld door invoer, wijziging en vervanging)."""

    dot_code: str | None = Field(default=None, max_length=20)
    purchase_date: date | None = None
    # Leeg = merk/model van de set.
    brand: str | None = Field(default=None, max_length=80)
    model: str | None = Field(default=None, max_length=80)
    # Alleen relevant bij winter- en vierseizoenenbanden.
    has_3pmsf: bool | None = None
    # Optioneel, bv. "FL,FR"; wordt genormaliseerd naar vaste volgorde.
    positions: str | None = Field(default=None, max_length=20)

    @field_validator("dot_code", "brand", "model", mode="before")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        return _blank_to_none(value) if isinstance(value, str) or value is None else value

    @field_validator("positions", mode="before")
    @classmethod
    def _positions(cls, value: str | None) -> str | None:
        if not isinstance(value, str):
            return value
        tokens = [
            _POSITION_ALIASES.get(t.upper(), t.upper())
            for t in value.replace(";", ",").replace(" ", ",").split(",")
            if t
        ]
        if not tokens:
            return None
        unknown = [t for t in tokens if t not in _POSITION_ORDER]
        if unknown:
            raise ValueError("posities zijn FL, FR, RL of RR (of LV, RV, LA, RA)")
        return ",".join(p for p in _POSITION_ORDER if p in tokens)


class TireGroupIn(TireGroupBase):
    quantity: int = Field(default=MAX_TIRES, ge=1, le=MAX_TIRES)


class TireGroupPatch(TireGroupBase):
    quantity: int | None = Field(default=None, ge=1, le=MAX_TIRES)


class TireGroupOut(TireGroupIn):
    id: int
    tire_set_id: int
    created_at: datetime
    removed_on: date | None = None
    removed_note: str | None = None
    # Productiedatum (maandag van de week) en leeftijd uit de DOT-code; `None` bij een ongeldige
    # code. Bij een vervangen groep is de leeftijd die op de dag van vervangen.
    produced_on: date | None = None
    age_years: float | None = None


class TireReplaceIn(TireGroupBase):
    """Banden vervangen: de nieuwe banden (DOT, aankoopdatum, merk, ...) staan in dezelfde velden."""

    group_id: int
    # Aantal te vervangen banden van de groep; leeg = de hele groep.
    quantity: int | None = Field(default=None, ge=1, le=MAX_TIRES)
    replaced_on: date | None = None
    note: str | None = Field(default=None, max_length=500)

    @field_validator("note", mode="before")
    @classmethod
    def _note(cls, value: str | None) -> str | None:
        return _blank_to_none(value) if isinstance(value, str) or value is None else value


class _TireSetFields(BaseModel):
    # Een oud veld als `dot_code` of `purchase_date` hoort nu bij een groep: liever een duidelijke
    # fout dan stilzwijgend negeren.
    model_config = ConfigDict(extra="forbid")


class TireSetIn(_TireSetFields):
    type: TireType
    brand: str | None = None
    model: str | None = None
    size: str | None = None
    purchase_price_cents: int | None = Field(default=None, ge=0)
    notes: str | None = None
    status: TireStatus = TireStatus.STORED
    # Leeg = één groep van 4 banden zonder DOT-code of aankoopdatum.
    tire_groups: list[TireGroupIn] | None = Field(default=None, max_length=MAX_TIRES)


class TireSetPatch(_TireSetFields):
    type: TireType | None = None
    brand: str | None = None
    model: str | None = None
    size: str | None = None
    purchase_price_cents: int | None = Field(default=None, ge=0)
    notes: str | None = None
    status: TireStatus | None = None


class TireSetOut(BaseModel):
    id: int
    vehicle_id: int
    type: TireType
    brand: str | None
    model: str | None
    size: str | None
    purchase_price_cents: int | None
    notes: str | None
    status: TireStatus
    created_at: datetime
    # Actieve groepen; met `include_removed` ook de vervangen groepen (geschiedenis).
    tire_groups: list[TireGroupOut]
    # Som van de aantallen van de actieve groepen (1-4; 4 is een complete set).
    tire_count: int
    # Leeftijd van de oudste band met een leesbare DOT-code, in jaren (één decimaal).
    oldest_tire_age_years: float | None
    # Winter- of vierseizoenenset waarvan alle actieve groepen het 3PMSF-symbool dragen.
    all_3pmsf: bool


class TreadMeasurementIn(BaseModel):
    measured_at: date
    position: Position
    depth_mm: float = Field(ge=0, le=20)


class TreadMeasurementOut(TreadMeasurementIn):
    id: int
    tire_set_id: int


class OdometerOut(BaseModel):
    id: int
    vehicle_id: int
    reading_km: int
    recorded_at: datetime
    source: OdometerSource
    superseded_by_id: int | None
    note: str | None


class TireChangeOut(BaseModel):
    id: int
    vehicle_id: int
    changed_at: date
    odometer_reading_id: int | None
    from_set_id: int | None
    to_set_id: int
    performed_by: ChangeMethod
    garage_id: int | None
    cost_cents: int | None
    notes: str | None


class KmInterval(BaseModel):
    """Eén montageperiode van een set; km is None als niet betrouwbaar te bepalen."""

    start_change_id: int | None
    end_change_id: int | None
    start_date: date | None
    end_date: date | None
    start_km: int | None
    end_km: int | None
    km: int | None


class KmSummary(BaseModel):
    known_km: int | None
    complete: bool
    intervals: list[KmInterval]
