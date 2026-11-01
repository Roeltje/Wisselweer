"""SQLAlchemy 2-modellen. Tijdstempels zijn UTC; datums zijn kalenderdatums."""

from __future__ import annotations

from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any

import sqlalchemy as sa
from sqlalchemy import CheckConstraint, ForeignKey, Index, UniqueConstraint, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from wisselweer.core.models import Direction, TireType
from wisselweer.storage.enums import (
    AppointmentStatus,
    ChangeMethod,
    OdometerSource,
    Position,
    TireStatus,
)


class UtcDateTime(sa.types.TypeDecorator[datetime]):
    """Bewaart tijdzone-bewuste datetimes als naïeve UTC; levert aware UTC terug."""

    impl = sa.DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("datetime moet tijdzone-bewust zijn")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        return None if value is None else value.replace(tzinfo=UTC)


def _enum(cls: type[StrEnum], name: str) -> sa.Enum:
    return sa.Enum(
        cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        values_callable=lambda e: [m.value for m in e],
        length=20,
    )


def _now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Location(Base):
    __tablename__ = "location"
    __table_args__ = (UniqueConstraint("latitude", "longitude", name="uq_location_coords"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(sa.String(120))
    latitude: Mapped[float]
    longitude: Mapped[float]
    timezone: Mapped[str] = mapped_column(sa.String(64), default="Europe/Amsterdam")


class Garage(Base):
    __tablename__ = "garage"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(sa.String(120))
    address: Mapped[str | None] = mapped_column(sa.String(255))
    phone: Mapped[str | None] = mapped_column(sa.String(40))
    email: Mapped[str | None] = mapped_column(sa.String(255))
    website: Mapped[str | None] = mapped_column(sa.String(255))
    notes: Mapped[str | None] = mapped_column(sa.Text)
    lead_time_days: Mapped[int] = mapped_column(default=14)


class Vehicle(Base):
    __tablename__ = "vehicle"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(sa.String(120))
    make: Mapped[str | None] = mapped_column(sa.String(80))
    model: Mapped[str | None] = mapped_column(sa.String(80))
    # Genormaliseerd (hoofdletters, zonder streepjes/spaties) voor zoeken/lookup.
    license_plate: Mapped[str | None] = mapped_column(sa.String(20), index=True)
    license_plate_display: Mapped[str | None] = mapped_column(sa.String(20))
    build_year: Mapped[int | None]
    location_id: Mapped[int] = mapped_column(ForeignKey("location.id"))
    timezone: Mapped[str] = mapped_column(sa.String(64), default="Europe/Amsterdam")
    driving_profile: Mapped[dict[str, Any]] = mapped_column(sa.JSON)
    change_method: Mapped[ChangeMethod] = mapped_column(
        _enum(ChangeMethod, "change_method"), default=ChangeMethod.SELF
    )
    preferred_garage_id: Mapped[int | None] = mapped_column(ForeignKey("garage.id"))
    prep_days: Mapped[int] = mapped_column(default=7)
    notes: Mapped[str | None] = mapped_column(sa.Text)
    countries_of_use: Mapped[list[str]] = mapped_column(sa.JSON, default=lambda: ["NL"])
    # Gereserveerd voor een toekomstige kentekenlookup; nu ongebruikt.
    plate_lookup_data: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON)
    # Alleen de bestandsnaam (`<32 hex>.<webp|jpg|png>`) in `<data_dir>/photos/`, nooit een pad.
    photo: Mapped[str | None] = mapped_column(sa.String(64))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now)


class TireSet(Base):
    __tablename__ = "tire_set"
    __table_args__ = (
        Index(
            "uq_tire_set_one_mounted",
            "vehicle_id",
            unique=True,
            sqlite_where=text("status = 'mounted'"),
            postgresql_where=text("status = 'mounted'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicle.id"), index=True)
    type: Mapped[TireType] = mapped_column(_enum(TireType, "tire_type"))
    brand: Mapped[str | None] = mapped_column(sa.String(80))
    model: Mapped[str | None] = mapped_column(sa.String(80))
    size: Mapped[str | None] = mapped_column(sa.String(40))
    purchase_price_cents: Mapped[int | None]
    notes: Mapped[str | None] = mapped_column(sa.Text)
    status: Mapped[TireStatus] = mapped_column(
        _enum(TireStatus, "tire_status"), default=TireStatus.STORED
    )
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now)


class TireGroup(Base):
    """Eén groep banden binnen een set (1-4 stuks met dezelfde DOT-code en aankoopdatum).

    Een set heeft standaard één groep van 4; afwijkende banden (bv. een vervangen band) krijgen
    een eigen groep. Actief = `removed_on IS NULL`; vervangen groepen blijven als geschiedenis staan.
    """

    __tablename__ = "tire_group"
    __table_args__ = (CheckConstraint("quantity BETWEEN 1 AND 4", name="ck_tire_group_quantity"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tire_set_id: Mapped[int] = mapped_column(ForeignKey("tire_set.id"), index=True)
    quantity: Mapped[int]
    dot_code: Mapped[str | None] = mapped_column(sa.String(20))
    purchase_date: Mapped[date | None]
    # Leeg = merk/model van de set.
    brand: Mapped[str | None] = mapped_column(sa.String(80))
    model: Mapped[str | None] = mapped_column(sa.String(80))
    # Alleen relevant bij winter- en vierseizoenenbanden; None = onbekend of niet van toepassing.
    has_3pmsf: Mapped[bool | None]
    # Optioneel, bv. "FL,FR".
    positions: Mapped[str | None] = mapped_column(sa.String(20))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now)
    removed_on: Mapped[date | None]
    removed_note: Mapped[str | None] = mapped_column(sa.String(500))


class TreadMeasurement(Base):
    __tablename__ = "tread_measurement"

    id: Mapped[int] = mapped_column(primary_key=True)
    tire_set_id: Mapped[int] = mapped_column(ForeignKey("tire_set.id"), index=True)
    measured_at: Mapped[date]
    position: Mapped[Position] = mapped_column(_enum(Position, "tread_position"))
    depth_mm: Mapped[float]


class OdometerReading(Base):
    __tablename__ = "odometer_reading"

    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicle.id"), index=True)
    reading_km: Mapped[int]
    recorded_at: Mapped[datetime] = mapped_column(UtcDateTime)
    source: Mapped[OdometerSource] = mapped_column(_enum(OdometerSource, "odometer_source"))
    # Correctie: nieuwe rij; de oude verwijst hiernaar. Rijen worden nooit verwijderd.
    superseded_by_id: Mapped[int | None] = mapped_column(ForeignKey("odometer_reading.id"))
    note: Mapped[str | None] = mapped_column(sa.Text)


class TireChange(Base):
    __tablename__ = "tire_change"

    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicle.id"), index=True)
    changed_at: Mapped[date]
    odometer_reading_id: Mapped[int | None] = mapped_column(ForeignKey("odometer_reading.id"))
    from_set_id: Mapped[int | None] = mapped_column(ForeignKey("tire_set.id"))
    to_set_id: Mapped[int] = mapped_column(ForeignKey("tire_set.id"))
    performed_by: Mapped[ChangeMethod] = mapped_column(_enum(ChangeMethod, "performed_by"))
    garage_id: Mapped[int | None] = mapped_column(ForeignKey("garage.id"))
    cost_cents: Mapped[int | None]
    notes: Mapped[str | None] = mapped_column(sa.Text)


class Appointment(Base):
    __tablename__ = "appointment"

    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicle.id"), index=True)
    garage_id: Mapped[int] = mapped_column(ForeignKey("garage.id"))
    status: Mapped[AppointmentStatus] = mapped_column(
        _enum(AppointmentStatus, "appointment_status"), default=AppointmentStatus.NOT_PLANNED
    )
    target_direction: Mapped[Direction] = mapped_column(_enum(Direction, "target_direction"))
    target_period_start: Mapped[date | None]
    target_period_end: Mapped[date | None]
    appointment_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    notes: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now)


class ForecastCache(Base):
    __tablename__ = "forecast_cache"

    key: Mapped[str] = mapped_column(sa.String(120), primary_key=True)
    provider: Mapped[str] = mapped_column(sa.String(40))
    latitude: Mapped[float]
    longitude: Mapped[float]
    forecast: Mapped[dict[str, Any]] = mapped_column(sa.JSON)
    fetched_at: Mapped[datetime] = mapped_column(UtcDateTime)
    expires: Mapped[datetime | None] = mapped_column(UtcDateTime)
    last_modified: Mapped[str | None] = mapped_column(sa.String(80))


class ForecastSnapshot(Base):
    """Eén per (provider, locatie, fetch) voor backtests."""

    __tablename__ = "forecast_snapshot"
    __table_args__ = (
        UniqueConstraint(
            "provider", "latitude", "longitude", "fetched_at", name="uq_forecast_snapshot_fetch"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(sa.String(40))
    latitude: Mapped[float]
    longitude: Mapped[float]
    fetched_at: Mapped[datetime] = mapped_column(UtcDateTime)
    forecast: Mapped[dict[str, Any]] = mapped_column(sa.JSON)


class AdviceSnapshot(Base):
    __tablename__ = "advice_snapshot"

    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int | None] = mapped_column(ForeignKey("vehicle.id"), index=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("location.id"))
    evaluated_at: Mapped[datetime] = mapped_column(UtcDateTime)
    advice: Mapped[dict[str, Any]] = mapped_column(sa.JSON)
    forecast_snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("forecast_snapshot.id"))
    rules_version: Mapped[str] = mapped_column(sa.String(20))
    # Gezet bij een bandenwissel: reset van de hysterese; rij blijft bewaard voor backtests.
    invalidated_at: Mapped[datetime | None] = mapped_column(UtcDateTime)


class AppSetting(Base):
    __tablename__ = "app_setting"

    key: Mapped[str] = mapped_column(sa.String(80), primary_key=True)
    value: Mapped[Any] = mapped_column(sa.JSON)


class AdminUser(Base):
    __tablename__ = "admin_user"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(sa.String(80), unique=True)
    password_hash: Mapped[str] = mapped_column(sa.String(255))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now)


class ApiToken(Base):
    """Bearer-token voor integraties; alleen de SHA-256-hash wordt bewaard."""

    __tablename__ = "api_token"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(sa.String(80))
    token_hash: Mapped[str] = mapped_column(sa.String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now)
    last_used_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
