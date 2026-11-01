"""Banden per groep: migratie (op en neer met bestaande data) en serviceregels."""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy import select

import wisselweer.storage.db as storage_db
from tests.integration.conftest import vehicle_in
from wisselweer.core import TireType
from wisselweer.storage.enums import TireStatus
from wisselweer.storage.errors import InvalidOperation, NotFoundError
from wisselweer.storage.orm import TireGroup, TireSet
from wisselweer.tires import service as tsvc
from wisselweer.tires.schemas import (
    TireGroupIn,
    TireGroupPatch,
    TireReplaceIn,
    TireSetIn,
    TireSetPatch,
)
from wisselweer.vehicles import service as vsvc

TODAY = date(2026, 11, 1)


# --- Migratie 0003 ----------------------------------------------------------------------


def _cfg(url: str) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(Path(storage_db.__file__).parent / "migrations"))
    cfg.attributes["url"] = url
    return cfg


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def test_migratie_op_en_neer_met_bestaande_data(tmp_path):
    db = tmp_path / "m.db"
    cfg = _cfg(f"sqlite:///{db}")
    command.upgrade(cfg, "0002")

    # Database zoals die vóór deze wijziging bestond, met data en verwijzingen naar tire_set.
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(
        "INSERT INTO location(name, latitude, longitude, timezone) VALUES ('U', 52, 5, 'UTC')"
    )
    conn.execute(
        "INSERT INTO vehicle(name, location_id, timezone, driving_profile, change_method, "
        "prep_days, countries_of_use, created_at, updated_at) "
        "VALUES ('A', 1, 'UTC', '{}', 'self', 7, '[\"NL\"]', '2026-01-01', '2026-01-01')"
    )
    conn.execute(
        "INSERT INTO tire_set(vehicle_id, type, dot_code, purchase_date, status, created_at) "
        "VALUES (1, 'summer', 'DOT 2319', '2020-05-01', 'mounted', '2026-01-01 00:00:00')"
    )
    conn.execute(
        "INSERT INTO tire_set(vehicle_id, type, status, created_at) "
        "VALUES (1, 'winter', 'stored', '2026-01-02 00:00:00')"
    )
    conn.execute(
        "INSERT INTO tread_measurement(tire_set_id, measured_at, position, depth_mm) "
        "VALUES (1, '2026-01-01', 'FL', 6)"
    )
    conn.execute(
        "INSERT INTO tire_change(vehicle_id, changed_at, from_set_id, to_set_id, performed_by) "
        "VALUES (1, '2026-01-01', 2, 1, 'self')"
    )
    conn.commit()
    conn.close()

    command.upgrade(cfg, "head")
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA foreign_keys=ON")
    groups = conn.execute(
        "SELECT tire_set_id, quantity, dot_code, purchase_date, removed_on, created_at "
        "FROM tire_group ORDER BY id"
    ).fetchall()
    assert groups == [
        (1, 4, "DOT 2319", "2020-05-01", None, "2026-01-01 00:00:00"),
        (2, 4, None, None, None, "2026-01-02 00:00:00"),
    ]
    assert {"dot_code", "purchase_date"}.isdisjoint(_columns(conn, "tire_set"))
    # Verwijzende tabellen en gegevens zijn intact.
    assert conn.execute("SELECT count(*) FROM tire_change").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM tread_measurement").fetchone()[0] == 1
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    # Een vervangen groep en een tweede actieve groep; de terugweg pakt de eerste actieve.
    conn.execute(
        "INSERT INTO tire_group(tire_set_id, quantity, dot_code, created_at, removed_on) "
        "VALUES (1, 2, '0112', '2026-01-01', '2026-02-01')"
    )
    conn.execute("UPDATE tire_group SET quantity = 2, dot_code = '1222' WHERE id = 1")
    conn.execute(
        "INSERT INTO tire_group(tire_set_id, quantity, dot_code, purchase_date, created_at) "
        "VALUES (1, 2, '5022', '2022-12-20', '2026-03-01')"
    )
    conn.commit()
    conn.close()

    command.downgrade(cfg, "0002")
    conn = sqlite3.connect(db)
    assert {"dot_code", "purchase_date"} <= _columns(conn, "tire_set")
    rows = conn.execute("SELECT id, dot_code, purchase_date FROM tire_set ORDER BY id").fetchall()
    assert rows == [(1, "1222", "2020-05-01"), (2, None, None)]
    assert conn.execute("SELECT name FROM sqlite_master WHERE name = 'tire_group'").fetchall() == []
    assert conn.execute("SELECT count(*) FROM tire_change").fetchone()[0] == 1
    conn.execute("PRAGMA foreign_keys=ON")
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    conn.close()

    command.upgrade(cfg, "head")  # en weer omhoog zonder fouten
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT count(*) FROM tire_group").fetchone()[0] == 2
    conn.close()


# --- Service ----------------------------------------------------------------------------


def _vehicle(session):
    return vsvc.create_vehicle(session, vehicle_in())


def _set(session, vid, groups=None, type_=TireType.WINTER, **kw):
    return tsvc.create_tire_set(session, vid, TireSetIn(type=type_, tire_groups=groups, **kw))


def _active(session, set_id):
    return [g for g in tsvc.get_tire_set(session, set_id).tire_groups]


def test_nieuwe_set_krijgt_standaard_een_groep_van_vier(session):
    v = _vehicle(session)
    out = _set(session, v.id)
    assert [(g.quantity, g.dot_code) for g in out.tire_groups] == [(4, None)]
    assert out.tire_count == 4
    assert out.oldest_tire_age_years is None
    assert not out.all_3pmsf


def test_set_met_meerdere_groepen_en_somgrenzen(session):
    v = _vehicle(session)
    out = _set(
        session,
        v.id,
        [TireGroupIn(quantity=2, dot_code="2319"), TireGroupIn(quantity=2, dot_code="1222")],
    )
    assert out.tire_count == 4
    with pytest.raises(InvalidOperation):
        _set(session, v.id, [TireGroupIn(quantity=3), TireGroupIn(quantity=2)])
    with pytest.raises(InvalidOperation):
        _set(session, v.id, [])  # minimaal één groep
    # Een som onder 4 mag (de UI waarschuwt alleen).
    assert _set(session, v.id, [TireGroupIn(quantity=1)]).tire_count == 1
    for bad in (0, 5):
        with pytest.raises(ValidationError):
            TireGroupIn(quantity=bad)
    with pytest.raises(ValidationError):
        TireSetIn(type=TireType.SUMMER, tire_groups=[TireGroupIn()] * 5)


def test_oude_setvelden_worden_geweigerd():
    with pytest.raises(ValidationError):
        TireSetIn(type=TireType.SUMMER, dot_code="2319")
    with pytest.raises(ValidationError):
        TireSetPatch(purchase_date="2020-01-01")


def test_leeftijd_oudste_band_en_3pmsf(session):
    v = _vehicle(session)
    out = _set(
        session,
        v.id,
        [
            TireGroupIn(quantity=2, dot_code="DOT X 2319", has_3pmsf=True),
            TireGroupIn(quantity=2, dot_code="ongeldig", has_3pmsf=True),
        ],
    )
    assert out.oldest_tire_age_years is not None and out.oldest_tire_age_years > 7
    ages = {g.dot_code: g.age_years for g in out.tire_groups}
    assert ages["ongeldig"] is None
    assert out.tire_groups[0].produced_on == date(2019, 6, 3)
    assert out.all_3pmsf
    # Eén groep zonder het symbool: niet meer "alle".
    tsvc.update_tire_group(session, out.tire_groups[1].id, TireGroupPatch(has_3pmsf=False))
    assert not tsvc.get_tire_set(session, out.id).all_3pmsf
    # Zomerbanden tellen nooit als 3PMSF, ook niet met de vlag.
    summer = _set(session, v.id, [TireGroupIn(has_3pmsf=True)], type_=TireType.SUMMER)
    assert not summer.all_3pmsf


def test_groep_toevoegen_wijzigen_en_somregel(session):
    v = _vehicle(session)
    s = _set(session, v.id, [TireGroupIn(quantity=2)])
    g2 = tsvc.add_tire_group(
        session, s.id, TireGroupIn(quantity=2, brand="Dunlop", positions="rv,lv")
    )
    assert g2.positions == "FL,FR"  # genormaliseerd, ook met Nederlandse afkortingen
    with pytest.raises(InvalidOperation):
        tsvc.add_tire_group(session, s.id, TireGroupIn(quantity=1))  # zou 5 worden
    with pytest.raises(InvalidOperation):
        tsvc.update_tire_group(session, g2.id, TireGroupPatch(quantity=3))  # 2 + 3 = 5
    assert tsvc.update_tire_group(session, g2.id, TireGroupPatch(quantity=1)).quantity == 1
    with pytest.raises(InvalidOperation):
        tsvc.update_tire_group(session, g2.id, TireGroupPatch.model_construct(quantity=None))
    with pytest.raises(NotFoundError):
        tsvc.add_tire_group(session, 9999, TireGroupIn())
    with pytest.raises(ValidationError):
        TireGroupIn(positions="XX")


def test_minimaal_een_actieve_groep(session):
    v = _vehicle(session)
    s = _set(session, v.id, [TireGroupIn(quantity=2), TireGroupIn(quantity=2)])
    first, second = s.tire_groups
    tsvc.delete_tire_group(session, first.id)
    with pytest.raises(InvalidOperation):
        tsvc.delete_tire_group(session, second.id)
    assert len(tsvc.get_tire_set(session, s.id).tire_groups) == 1
    with pytest.raises(NotFoundError):
        tsvc.delete_tire_group(session, 9999)


def test_vervangen_hele_groep_sluit_oude_af(session):
    v = _vehicle(session)
    s = _set(session, v.id, [TireGroupIn(quantity=4, dot_code="2319", brand="Oud")])
    old = s.tire_groups[0]
    out = tsvc.replace_tires(
        session,
        s.id,
        TireReplaceIn(group_id=old.id, dot_code="1224", brand="Nieuw", note="versleten"),
        today=TODAY,
    )
    assert [(g.quantity, g.dot_code, g.brand) for g in out.tire_groups] == [(4, "1224", "Nieuw")]
    history = tsvc.get_tire_set(session, s.id, include_removed=True).tire_groups
    assert [g.id for g in history][0] == old.id
    closed = history[0]
    assert closed.removed_on == TODAY and closed.removed_note == "versleten"
    assert closed.quantity == 4 and closed.dot_code == "2319"
    assert closed.age_years is not None  # leeftijd op de dag van vervangen


def test_vervangen_deel_splitst_de_groep(session):
    v = _vehicle(session)
    s = _set(
        session, v.id, [TireGroupIn(quantity=4, dot_code="2319", purchase_date=date(2019, 7, 1))]
    )
    old = s.tire_groups[0]
    out = tsvc.replace_tires(
        session,
        s.id,
        TireReplaceIn(
            group_id=old.id,
            quantity=1,
            dot_code="1226",
            positions="RL",
            replaced_on=date(2026, 10, 1),
        ),
        today=TODAY,
    )
    assert out.tire_count == 4  # som blijft gelijk
    assert sorted((g.quantity, g.dot_code) for g in out.tire_groups) == [(1, "1226"), (3, "2319")]
    everything = tsvc.get_tire_set(session, s.id, include_removed=True).tire_groups
    closed = [g for g in everything if g.removed_on]
    assert len(closed) == 1
    assert (closed[0].quantity, closed[0].dot_code, closed[0].removed_on) == (
        1,
        "2319",
        date(2026, 10, 1),
    )
    assert closed[0].purchase_date == date(2019, 7, 1)
    remaining = next(g for g in out.tire_groups if g.dot_code == "2319")
    assert remaining.id == old.id and remaining.quantity == 3
    # Daarna nog eens, nu twee banden van de overgebleven groep.
    out = tsvc.replace_tires(
        session, s.id, TireReplaceIn(group_id=old.id, quantity=2, dot_code="1226"), today=TODAY
    )
    assert out.tire_count == 4
    assert sorted(g.quantity for g in out.tire_groups) == [1, 1, 2]


def test_vervangen_validaties(session):
    v = _vehicle(session)
    s = _set(session, v.id, [TireGroupIn(quantity=2), TireGroupIn(quantity=2)])
    g1, g2 = s.tire_groups
    other = _set(session, v.id)
    with pytest.raises(InvalidOperation):  # meer dan de groep telt
        tsvc.replace_tires(session, s.id, TireReplaceIn(group_id=g1.id, quantity=3), today=TODAY)
    with pytest.raises(InvalidOperation):  # datum in de toekomst
        tsvc.replace_tires(
            session,
            s.id,
            TireReplaceIn(group_id=g1.id, replaced_on=date(2026, 12, 1)),
            today=TODAY,
        )
    with pytest.raises(NotFoundError):  # groep hoort bij een andere set
        tsvc.replace_tires(session, other.id, TireReplaceIn(group_id=g1.id), today=TODAY)
    with pytest.raises(NotFoundError):
        tsvc.replace_tires(session, s.id, TireReplaceIn(group_id=9999), today=TODAY)
    tsvc.replace_tires(session, s.id, TireReplaceIn(group_id=g2.id), today=TODAY)
    with pytest.raises(InvalidOperation):  # al vervangen
        tsvc.replace_tires(session, s.id, TireReplaceIn(group_id=g2.id), today=TODAY)
    with pytest.raises(InvalidOperation):  # vervangen groep niet meer wijzigen
        tsvc.update_tire_group(session, g2.id, TireGroupPatch(brand="X"))


def test_vervangen_is_atomair(session, monkeypatch):
    """Faalt het toevoegen van de nieuwe groep na het splitsen, dan blijft alles zoals het was."""
    v = _vehicle(session)
    s = _set(session, v.id, [TireGroupIn(quantity=4, dot_code="2319")])
    old = s.tire_groups[0]

    real_add = session.add
    calls = {"n": 0}

    def failing_add(obj, *args, **kwargs):
        if isinstance(obj, TireGroup):
            calls["n"] += 1
            if calls["n"] == 2:  # na de afgesloten kopie, bij de nieuwe groep
                raise RuntimeError("storing")
        return real_add(obj, *args, **kwargs)

    monkeypatch.setattr(session, "add", failing_add)
    with pytest.raises(RuntimeError):
        tsvc.replace_tires(
            session, s.id, TireReplaceIn(group_id=old.id, quantity=1, dot_code="1226"), today=TODAY
        )
    monkeypatch.undo()
    groups = list(session.scalars(select(TireGroup).where(TireGroup.tire_set_id == s.id)))
    assert [(g.quantity, g.dot_code, g.removed_on) for g in groups] == [(4, "2319", None)]


def test_set_verwijderen_ruimt_groepen_op(session):
    v = _vehicle(session)
    s = _set(
        session, v.id, [TireGroupIn(quantity=2), TireGroupIn(quantity=2)], status=TireStatus.STORED
    )
    tsvc.delete_tire_set(session, s.id)
    assert session.scalar(select(TireGroup).where(TireGroup.tire_set_id == s.id)) is None
    s2 = _set(session, v.id)
    vsvc.delete_vehicle(session, v.id)
    assert session.get(TireSet, s2.id) is None
    assert session.scalar(select(TireGroup)) is None
