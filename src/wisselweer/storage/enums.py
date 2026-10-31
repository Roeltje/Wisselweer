"""Waardelijsten van de opslaglaag (als strings in de database)."""

from __future__ import annotations

from enum import StrEnum


class TireStatus(StrEnum):
    MOUNTED = "mounted"
    STORED = "stored"
    RETIRED = "retired"


class ChangeMethod(StrEnum):
    SELF = "self"
    GARAGE = "garage"


class Position(StrEnum):
    FL = "FL"
    FR = "FR"
    RL = "RL"
    RR = "RR"
    ALL = "ALL"


class OdometerSource(StrEnum):
    TIRE_CHANGE = "tire_change"
    MANUAL = "manual"


class AppointmentStatus(StrEnum):
    NOT_PLANNED = "not_planned"
    TO_REQUEST = "to_request"
    REQUESTED = "requested"
    CONFIRMED = "confirmed"
    DONE = "done"
    CANCELLED = "cancelled"


# Toegestane statusovergangen van een afspraak.
APPOINTMENT_TRANSITIONS: dict[AppointmentStatus, frozenset[AppointmentStatus]] = {
    AppointmentStatus.NOT_PLANNED: frozenset(
        {AppointmentStatus.TO_REQUEST, AppointmentStatus.CANCELLED}
    ),
    AppointmentStatus.TO_REQUEST: frozenset(
        {
            AppointmentStatus.NOT_PLANNED,
            AppointmentStatus.REQUESTED,
            AppointmentStatus.CANCELLED,
        }
    ),
    AppointmentStatus.REQUESTED: frozenset(
        {
            AppointmentStatus.TO_REQUEST,
            AppointmentStatus.CONFIRMED,
            AppointmentStatus.CANCELLED,
        }
    ),
    AppointmentStatus.CONFIRMED: frozenset(
        {
            AppointmentStatus.REQUESTED,
            AppointmentStatus.DONE,
            AppointmentStatus.CANCELLED,
        }
    ),
    AppointmentStatus.DONE: frozenset(),
    AppointmentStatus.CANCELLED: frozenset(
        {AppointmentStatus.NOT_PLANNED, AppointmentStatus.TO_REQUEST}
    ),
}
