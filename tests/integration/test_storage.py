from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from urllib.parse import parse_qs, unquote, urlsplit

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import func, inspect, select
from sqlalchemy.exc import IntegrityError

from tests.fixtures.builders import Day, make_forecast
from tests.integration.conftest import vehicle_in
from wisselweer.core import Advice, AdviceStatus, Direction, TireType
from wisselweer.core.models import Forecast
from wisselweer.garages import service as gsvc
from wisselweer.garages.schemas import AppointmentIn, GarageIn
from wisselweer.storage.cache_backend import SqliteCacheBackend
from wisselweer.storage.enums import AppointmentStatus as AS
from wisselweer.storage.enums import ChangeMethod, TireStatus
from wisselweer.storage.errors import InvalidOperation, NotFoundError
from wisselweer.storage.orm import (
    AdviceSnapshot,
    Base,
    ForecastSnapshot,
    Location,
    OdometerReading,
    TireChange,
    TireSet,
    TreadMeasurement,
)
from wisselweer.tires import service as tsvc
from wisselweer.tires.schemas import TireSetIn, TireSetPatch, TreadMeasurementIn
from wisselweer.vehicles import service as vsvc
from wisselweer.vehicles.schemas import LocationIn, VehiclePatch
from wisselweer.weather.cache import CacheEntry

TODAY = date(2026, 10, 31)


def _vehicle(session, **kw):
    return vsvc.create_vehicle(session, vehicle_in(**kw))


def _set(session, vid, type_=TireType.SUMMER, status=TireStatus.STORED):
    return tsvc.create_tire_set(session, vid, TireSetIn(type=type_, status=status))


# --- Voertuigen -------------------------------------------------------------------------


def test_vehicle_crud_and_plate(session):
    v = _vehicle(session, plate="xx-000-x")
    assert v.license_plate == "XX-000-X"
    assert v.license_plate_normalized == "XX000X"
    assert v.countries_of_use == ["NL"]
    assert vsvc.get_vehicle(session, v.id).name == "Testauto"
    out = vsvc.update_vehicle(
        session, v.id, VehiclePatch(name="Nieuw", license_plate=None, prep_days=3)
    )
    assert out.name == "Nieuw" and out.license_plate is None and out.prep_days == 3
    assert out.make is None
    assert len(vsvc.list_vehicles(session)) == 1
    vsvc.delete_vehicle(session, v.id)
    with pytest.raises(NotFoundError):
        vsvc.get_vehicle(session, v.id)


def test_location_reuse_rounded(session):
    a = _vehicle(session, name="A")
    b = _vehicle(
        session,
        name="B",
        location=LocationIn(name="Elders", latitude=52.09071, longitude=5.12142),
    )
    c = _vehicle(session, name="C", location=LocationIn(name="Ver", latitude=51.0, longitude=4.0))
    assert a.location.id == b.location.id != c.location.id
    assert session.scalar(select(func.count()).select_from(Location)) == 2


def test_delete_vehicle_cascades(session):
    v = _vehicle(session)
    s1 = _set(session, v.id, status=TireStatus.MOUNTED)
    s2 = _set(session, v.id, TireType.WINTER)
    tsvc.add_tread_measurement(
        session, s1.id, TreadMeasurementIn(measured_at=TODAY, position="ALL", depth_mm=6)
    )
    tsvc.register_tire_change(session, v.id, s2.id, TODAY, odometer_km=1000, today=TODAY)
    r = session.scalar(select(OdometerReading))
    tsvc.correct_odometer(session, r.id, 1100)
    other = _vehicle(session, name="Ander")
    vsvc.delete_vehicle(session, v.id)
    for model in (TireSet, TireChange, OdometerReading, TreadMeasurement):
        assert session.scalar(select(func.count()).select_from(model)) == 0
    assert vsvc.get_vehicle(session, other.id)


# --- Sets en unieke gemonteerde set -----------------------------------------------------


def test_multiple_sets_single_mounted_service(session):
    v = _vehicle(session)
    _set(session, v.id, status=TireStatus.MOUNTED)
    _set(session, v.id, TireType.WINTER)
    _set(session, v.id, TireType.ALL_SEASON)
    assert len(tsvc.list_tire_sets(session, v.id)) == 3
    with pytest.raises(InvalidOperation):
        _set(session, v.id, status=TireStatus.MOUNTED)
    w = tsvc.list_tire_sets(session, v.id)[1]
    with pytest.raises(InvalidOperation):
        tsvc.update_tire_set(session, w.id, TireSetPatch(status=TireStatus.MOUNTED))
    out = tsvc.update_tire_set(session, w.id, TireSetPatch(brand="Merk"))
    assert out.brand == "Merk"


def test_single_mounted_db_level(session):
    v = _vehicle(session)
    v2 = _vehicle(session, name="Twee")
    session.add(TireSet(vehicle_id=v.id, type=TireType.SUMMER, status=TireStatus.MOUNTED))
    session.add(TireSet(vehicle_id=v2.id, type=TireType.SUMMER, status=TireStatus.MOUNTED))
    session.flush()  # ander voertuig mag wel
    session.add(TireSet(vehicle_id=v.id, type=TireType.WINTER, status=TireStatus.MOUNTED))
    with pytest.raises(IntegrityError):
        session.flush()


def test_tread_measurements(session):
    v = _vehicle(session)
    s = _set(session, v.id)
    tsvc.add_tread_measurement(
        session, s.id, TreadMeasurementIn(measured_at=TODAY, position="FL", depth_mm=7.5)
    )
    out = tsvc.list_tread_measurements(session, s.id)
    assert len(out) == 1 and out[0].depth_mm == 7.5
    with pytest.raises(NotFoundError):
        tsvc.add_tread_measurement(
            session, 999, TreadMeasurementIn(measured_at=TODAY, position="FL", depth_mm=1)
        )


# --- Wissels en km ----------------------------------------------------------------------


def _two_sets(session):
    v = _vehicle(session)
    summer = _set(session, v.id, TireType.SUMMER, TireStatus.MOUNTED)
    winter = _set(session, v.id, TireType.WINTER)
    return v, summer, winter


def test_change_history_and_statuses(session):
    v, summer, winter = _two_sets(session)
    c = tsvc.register_tire_change(
        session, v.id, winter.id, date(2026, 10, 1), odometer_km=10000, today=TODAY
    )
    assert c.from_set_id == summer.id and c.to_set_id == winter.id
    assert tsvc.get_tire_set(session, summer.id).status == TireStatus.STORED
    assert tsvc.get_tire_set(session, winter.id).status == TireStatus.MOUNTED
    tsvc.register_tire_change(
        session,
        v.id,
        summer.id,
        date(2027, 4, 1) if False else date(2026, 10, 20),
        odometer_km=10500,
        today=TODAY,
    )
    hist = tsvc.list_tire_changes(session, v.id)
    assert [h.to_set_id for h in hist] == [winter.id, summer.id]


def test_change_validation(session):
    v, summer, winter = _two_sets(session)
    other = _vehicle(session, name="Ander")
    foreign = _set(session, other.id, TireType.WINTER)
    with pytest.raises(InvalidOperation):
        tsvc.register_tire_change(session, v.id, foreign.id, TODAY, today=TODAY)
    with pytest.raises(InvalidOperation):
        tsvc.register_tire_change(session, v.id, winter.id, TODAY + timedelta(days=1), today=TODAY)
    with pytest.raises(InvalidOperation):
        tsvc.register_tire_change(session, v.id, summer.id, TODAY, today=TODAY)  # al gemonteerd
    tsvc.register_tire_change(
        session, v.id, winter.id, date(2026, 10, 1), odometer_km=5000, today=TODAY
    )
    with pytest.raises(InvalidOperation):
        tsvc.register_tire_change(
            session, v.id, summer.id, date(2026, 10, 15), odometer_km=4000, today=TODAY
        )
    # expliciete correctie toegestaan
    tsvc.register_tire_change(
        session,
        v.id,
        summer.id,
        date(2026, 10, 15),
        odometer_km=4000,
        allow_lower_odometer=True,
        today=TODAY,
    )


def test_change_rollback_midway(session, monkeypatch):
    v, summer, winter = _two_sets(session)
    session.commit()

    def boom(*a, **k):
        raise RuntimeError("fout midden in de wissel")

    monkeypatch.setattr(tsvc, "_invalidate_advice", boom)
    with pytest.raises(RuntimeError):
        tsvc.register_tire_change(
            session, v.id, winter.id, date(2026, 10, 1), odometer_km=100, today=TODAY
        )
    session.expire_all()
    assert tsvc.get_tire_set(session, summer.id).status == TireStatus.MOUNTED
    assert tsvc.get_tire_set(session, winter.id).status == TireStatus.STORED
    assert session.scalar(select(func.count()).select_from(TireChange)) == 0
    assert session.scalar(select(func.count()).select_from(OdometerReading)) == 0


def test_change_invalidates_advice_snapshots(session):
    v, summer, winter = _two_sets(session)
    loc_id = v.location.id
    session.add(
        AdviceSnapshot(
            vehicle_id=v.id,
            location_id=loc_id,
            evaluated_at=datetime.now(UTC),
            advice={},
            rules_version="x",
        )
    )
    session.flush()
    tsvc.register_tire_change(session, v.id, winter.id, TODAY, today=TODAY)
    snap = session.scalar(select(AdviceSnapshot))
    assert snap.invalidated_at is not None


def test_km_per_set(session):
    v, summer, winter = _two_sets(session)
    # zomer was al gemonteerd zonder vastgelegde montage => onbekend interval
    tsvc.register_tire_change(
        session, v.id, winter.id, date(2026, 10, 1), odometer_km=10000, today=TODAY
    )
    km = tsvc.km_per_set(session, summer.id)
    assert km.known_km is None and not km.complete
    # winter nog gemonteerd: laatste bekende stand = montagestand => 0
    km = tsvc.km_per_set(session, winter.id)
    assert km.known_km == 0 and km.complete
    tsvc.add_odometer_reading(session, v.id, 10800, datetime(2026, 10, 20, tzinfo=UTC))
    km = tsvc.km_per_set(session, winter.id)
    assert km.known_km == 800 and km.complete and km.intervals[0].end_change_id is None
    # terugwisselen en weer winter: twee intervallen
    tsvc.register_tire_change(
        session, v.id, summer.id, date(2026, 10, 25), odometer_km=11000, today=TODAY
    )
    km = tsvc.km_per_set(session, winter.id)
    assert km.known_km == 1000 and km.complete
    tsvc.register_tire_change(
        session, v.id, winter.id, date(2026, 10, 28), odometer_km=11200, today=TODAY
    )
    tsvc.add_odometer_reading(session, v.id, 11500, datetime(2026, 10, 30, tzinfo=UTC))
    km = tsvc.km_per_set(session, winter.id)
    assert km.known_km == 1300 and len(km.intervals) == 2 and km.complete


def test_km_missing_reading_and_negative(session):
    v, summer, winter = _two_sets(session)
    tsvc.register_tire_change(
        session, v.id, winter.id, date(2026, 10, 1), odometer_km=None, today=TODAY
    )
    tsvc.register_tire_change(
        session, v.id, summer.id, date(2026, 10, 10), odometer_km=2000, today=TODAY
    )
    km = tsvc.km_per_set(session, winter.id)  # start onbekend
    assert km.known_km is None and not km.complete
    # negatief verschil door expliciet toegestane lagere stand
    tsvc.register_tire_change(
        session, v.id, winter.id, date(2026, 10, 20), odometer_km=3000, today=TODAY
    )
    tsvc.register_tire_change(
        session,
        v.id,
        summer.id,
        date(2026, 10, 25),
        odometer_km=2500,
        allow_lower_odometer=True,
        today=TODAY,
    )
    km = tsvc.km_per_set(session, winter.id)
    ivs = km.intervals
    assert ivs[-1].km is None and ivs[-1].start_km == 3000 and ivs[-1].end_km == 2500
    assert not km.complete


def test_correct_odometer(session):
    v, summer, winter = _two_sets(session)
    tsvc.register_tire_change(
        session, v.id, winter.id, date(2026, 10, 1), odometer_km=1000, today=TODAY
    )
    tsvc.register_tire_change(
        session, v.id, summer.id, date(2026, 10, 10), odometer_km=1500, today=TODAY
    )
    assert tsvc.km_per_set(session, winter.id).known_km == 500
    old = tsvc.list_odometer_readings(session, v.id)[0]
    new = tsvc.correct_odometer(session, old.id, 1200, note="typfout")
    assert new.reading_km == 1200 and new.id != old.id
    all_rows = tsvc.list_odometer_readings(session, v.id, include_superseded=True)
    assert len(all_rows) == 3
    assert [r.superseded_by_id for r in all_rows if r.id == old.id] == [new.id]
    assert tsvc.km_per_set(session, winter.id).known_km == 300
    with pytest.raises(InvalidOperation):
        tsvc.correct_odometer(session, old.id, 1)
    with pytest.raises(NotFoundError):
        tsvc.correct_odometer(session, 9999, 1)


# --- Garages en afspraken ---------------------------------------------------------------


def test_garage_shared_by_vehicles(session):
    g = gsvc.create_garage(
        session, GarageIn(name="Garage Test", email="garage@example.invalid", lead_time_days=21)
    )
    a = _vehicle(session, name="A", preferred_garage_id=g.id, change_method=ChangeMethod.GARAGE)
    b = _vehicle(session, name="B", preferred_garage_id=g.id, change_method=ChangeMethod.GARAGE)
    assert a.preferred_garage_id == b.preferred_garage_id == g.id
    with pytest.raises(NotFoundError):
        _vehicle(session, name="C", preferred_garage_id=999)
    gsvc.create_appointment(
        session,
        AppointmentIn(vehicle_id=a.id, garage_id=g.id, target_direction=Direction.TO_WINTER),
    )
    with pytest.raises(InvalidOperation):
        gsvc.delete_garage(session, g.id)
    g2 = gsvc.create_garage(session, GarageIn(name="Leeg"))
    gsvc.delete_garage(session, g2.id)
    assert len(gsvc.list_garages(session)) == 1


def test_appointment_state_machine(session):
    g = gsvc.create_garage(session, GarageIn(name="G"))
    v = _vehicle(session)
    a = gsvc.create_appointment(
        session,
        AppointmentIn(vehicle_id=v.id, garage_id=g.id, target_direction=Direction.TO_WINTER),
    )
    assert a.status == AS.NOT_PLANNED
    for bad in (AS.DONE, AS.CONFIRMED, AS.REQUESTED):
        with pytest.raises(InvalidOperation):
            gsvc.set_appointment_status(session, a.id, bad)
    gsvc.set_appointment_status(session, a.id, AS.TO_REQUEST)
    gsvc.set_appointment_status(session, a.id, AS.REQUESTED)
    with pytest.raises(InvalidOperation):
        gsvc.set_appointment_status(session, a.id, AS.CONFIRMED)  # tijdstip ontbreekt
    when = datetime(2026, 11, 5, 9, 0, tzinfo=UTC)
    out = gsvc.set_appointment_status(session, a.id, AS.CONFIRMED, appointment_at=when)
    assert out.appointment_at == when
    gsvc.set_appointment_status(session, a.id, AS.DONE)
    with pytest.raises(InvalidOperation):
        gsvc.set_appointment_status(session, a.id, AS.CANCELLED)  # done is eindstatus
    with pytest.raises(NotFoundError):
        gsvc.set_appointment_status(session, 999, AS.DONE)


def test_mailto(session):
    g = gsvc.create_garage(session, GarageIn(name="Garage & Zn", email="garage@example.invalid"))
    v = _vehicle(session, name="Auto & Zo")
    adv = Advice(
        direction=Direction.TO_WINTER,
        heading="h",
        status=AdviceStatus.PREPARE_CHANGE,
        recommended_period=(date(2026, 11, 2), date(2026, 11, 9)),
        evaluated_at=datetime(2026, 10, 31, tzinfo=UTC),
    )
    url = gsvc.mailto_link(v, g, adv)
    assert url.startswith("mailto:garage@example.invalid?")
    assert " " not in url and "\n" not in url and "&body=" in url
    parts = urlsplit(url)
    q = parse_qs(parts.query, keep_blank_values=True)
    assert q["subject"] == ["Afspraak bandenwissel Auto & Zo"]
    body = q["body"][0]
    assert "Kenteken: XX-000-X" in body and "winterbanden" in body
    assert "02-11-2026" in body and "09-11-2026" in body and "Garage & Zn" in body
    assert "\r\n" in body and "%0D%0A" in url and "%26" in url
    assert unquote(parts.query).count("Auto & Zo") >= 1
    no_advice = gsvc.mailto_link(v, g, None)
    assert "Voorgestelde periode" not in unquote(no_advice)
    bare = gsvc.create_garage(session, GarageIn(name="Zonder"))
    with pytest.raises(InvalidOperation):
        gsvc.mailto_link(v, bare, adv)


# --- Cache en migraties -----------------------------------------------------------------


def test_sqlite_cache_backend(factory):
    backend = SqliteCacheBackend(factory)
    assert backend.get("k") is None
    fc = make_forecast(date(2026, 10, 31), [Day(2, 8)] * 2)
    now = datetime(2026, 10, 31, 8, tzinfo=UTC)
    backend.put(
        "k",
        CacheEntry(
            forecast=fc, fetched_at=now, expires=now + timedelta(hours=1), last_modified="lm"
        ),
    )
    got = backend.get("k")
    assert got.forecast == fc and got.fetched_at == now and got.last_modified == "lm"
    backend.put("k", CacheEntry(forecast=fc, fetched_at=now + timedelta(hours=2)))
    got = backend.get("k")
    assert got.expires is None and got.last_modified is None
    assert isinstance(got.forecast, Forecast)


def test_migration_matches_models(engine):
    insp = inspect(engine)
    assert set(Base.metadata.tables) <= set(insp.get_table_names())
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []


def test_migrate_idempotent_and_pragmas(db_url, engine):
    from wisselweer.storage.db import migrate

    migrate(db_url)
    with engine.connect() as c:
        assert c.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
        assert c.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"


def test_forecast_snapshot_unique_per_fetch(session):
    fc = make_forecast(date(2026, 10, 31), [Day(2, 8)])
    session.add(
        ForecastSnapshot(
            provider="p", latitude=1, longitude=2, fetched_at=fc.fetched_at, forecast={}
        )
    )
    session.flush()
    session.add(
        ForecastSnapshot(
            provider="p", latitude=1, longitude=2, fetched_at=fc.fetched_at, forecast={}
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()
