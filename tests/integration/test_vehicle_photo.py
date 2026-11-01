"""Voertuigfoto: migratie 0004 en de servicelaag (bestanden volgen de transactie)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select

import wisselweer.storage.db as storage_db
from tests.fixtures.images import make_jpeg, make_jpeg_with_exif, make_png
from tests.integration.conftest import vehicle_in
from wisselweer.storage.errors import NotFoundError
from wisselweer.storage.orm import Vehicle
from wisselweer.vehicles import service as vsvc
from wisselweer.vehicles.photos import PhotoError
from wisselweer.vehicles.schemas import VehicleOut, VehiclePatch

# --- Migratie 0004 ----------------------------------------------------------------------------


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
    command.upgrade(cfg, "0003")
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
        "INSERT INTO tire_set(vehicle_id, type, status, created_at) "
        "VALUES (1, 'summer', 'mounted', '2026-01-01 00:00:00')"
    )
    conn.commit()
    assert "photo" not in _columns(conn, "vehicle")
    conn.close()

    command.upgrade(cfg, "head")
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA foreign_keys=ON")
    assert "photo" in _columns(conn, "vehicle")
    assert conn.execute("SELECT name, photo FROM vehicle").fetchall() == [("A", None)]
    conn.execute("UPDATE vehicle SET photo = '0123456789abcdef0123456789abcdef.jpg'")
    conn.commit()
    assert conn.execute("SELECT count(*) FROM tire_set").fetchone()[0] == 1
    conn.close()

    command.downgrade(cfg, "0003")
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA foreign_keys=ON")
    assert "photo" not in _columns(conn, "vehicle")
    assert conn.execute("SELECT name FROM vehicle").fetchall() == [("A",)]
    assert conn.execute("SELECT count(*) FROM tire_set").fetchone()[0] == 1
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    conn.close()

    command.upgrade(cfg, "head")  # en weer omhoog zonder fouten


# --- Service ----------------------------------------------------------------------------------


@pytest.fixture
def photos_dir(tmp_path):
    return tmp_path / "photos"


def _names(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir()) if folder.exists() else []


def test_set_photo_schrijft_eerst_het_bestand_en_zet_de_naam(session, photos_dir):
    v = vsvc.create_vehicle(session, vehicle_in())
    assert v.has_photo is False
    out = vsvc.set_photo(session, v.id, make_jpeg_with_exif(), photos_dir)
    session.commit()
    (name,) = _names(photos_dir)
    assert out.has_photo is True and out.photo_version == name[:8]
    assert vsvc.get_photo_name(session, v.id) == name
    assert b"GPS" not in (photos_dir / name).read_bytes()
    assert vsvc.get_vehicle(session, v.id).has_photo is True


def test_oud_bestand_verdwijnt_pas_na_de_commit(session, photos_dir):
    v = vsvc.create_vehicle(session, vehicle_in())
    vsvc.set_photo(session, v.id, make_jpeg(), photos_dir)
    session.commit()
    (old,) = _names(photos_dir)

    vsvc.set_photo(session, v.id, make_png(), photos_dir)
    assert old in _names(photos_dir) and len(_names(photos_dir)) == 2  # nog niet gecommit
    session.commit()
    (new,) = _names(photos_dir)
    assert new != old and new.endswith(".png")


def test_rollback_ruimt_het_nieuwe_bestand_op_en_laat_het_oude_staan(session, photos_dir):
    v = vsvc.create_vehicle(session, vehicle_in())
    vsvc.set_photo(session, v.id, make_jpeg(), photos_dir)
    session.commit()
    (old,) = _names(photos_dir)

    vsvc.set_photo(session, v.id, make_png(), photos_dir)
    session.rollback()
    assert _names(photos_dir) == [old]
    assert vsvc.get_photo_name(session, v.id) == old
    # Een latere commit mag het (inmiddels teruggedraaide) oude bestand niet alsnog wissen.
    vsvc.update_vehicle(session, v.id, VehiclePatch(notes="x"))
    session.commit()
    assert _names(photos_dir) == [old]


def test_ongeldige_foto_verandert_niets(session, photos_dir):
    v = vsvc.create_vehicle(session, vehicle_in())
    session.commit()
    for bad in (b"GIF89a", make_jpeg()[:30], b"", b"\xff\xd8\xff" + bytes(3_000_000)):
        with pytest.raises(PhotoError):
            vsvc.set_photo(session, v.id, bad, photos_dir)
    assert not photos_dir.exists()
    assert vsvc.get_photo_name(session, v.id) is None


def test_set_photo_onbekend_voertuig(session, photos_dir):
    with pytest.raises(NotFoundError):
        vsvc.set_photo(session, 999, make_jpeg(), photos_dir)
    assert not photos_dir.exists()


def test_clear_photo(session, photos_dir):
    v = vsvc.create_vehicle(session, vehicle_in())
    vsvc.set_photo(session, v.id, make_jpeg(), photos_dir)
    session.commit()
    out = vsvc.clear_photo(session, v.id, photos_dir)
    assert out.has_photo is False and out.photo_version is None
    assert len(_names(photos_dir)) == 1  # pas weg na de commit
    session.commit()
    assert _names(photos_dir) == []
    assert vsvc.clear_photo(session, v.id, photos_dir).has_photo is False  # idempotent


def test_clear_photo_met_rollback_laat_het_bestand_staan(session, photos_dir):
    v = vsvc.create_vehicle(session, vehicle_in())
    vsvc.set_photo(session, v.id, make_jpeg(), photos_dir)
    session.commit()
    vsvc.clear_photo(session, v.id, photos_dir)
    session.rollback()
    assert len(_names(photos_dir)) == 1 and vsvc.get_vehicle(session, v.id).has_photo is True


def test_delete_vehicle_verwijdert_het_bestand_na_de_commit(session, photos_dir):
    a = vsvc.create_vehicle(session, vehicle_in())
    b = vsvc.create_vehicle(session, vehicle_in(name="Tweede", plate="YY-111-Y"))
    vsvc.set_photo(session, a.id, make_jpeg(), photos_dir)
    vsvc.set_photo(session, b.id, make_png(), photos_dir)
    session.commit()
    keep = vsvc.get_photo_name(session, b.id)

    vsvc.delete_vehicle(session, a.id, photos_dir)
    assert len(_names(photos_dir)) == 2
    session.commit()
    assert _names(photos_dir) == [keep]
    assert session.scalar(select(Vehicle).where(Vehicle.id == a.id)) is None


def test_delete_vehicle_met_rollback_laat_het_bestand_staan(session, photos_dir):
    a = vsvc.create_vehicle(session, vehicle_in())
    vsvc.set_photo(session, a.id, make_jpeg(), photos_dir)
    session.commit()
    vsvc.delete_vehicle(session, a.id, photos_dir)
    session.rollback()
    assert len(_names(photos_dir)) == 1 and vsvc.get_vehicle(session, a.id).has_photo is True


def test_delete_vehicle_zonder_fotomap_raakt_geen_bestanden(session, photos_dir):
    a = vsvc.create_vehicle(session, vehicle_in())
    vsvc.set_photo(session, a.id, make_jpeg(), photos_dir)
    session.commit()
    vsvc.delete_vehicle(session, a.id)  # compatibel met oude aanroepen
    session.commit()
    assert len(_names(photos_dir)) == 1


def test_fout_bij_verwijderen_van_bestand_laat_de_commit_slagen(session, photos_dir, monkeypatch):
    a = vsvc.create_vehicle(session, vehicle_in())
    vsvc.set_photo(session, a.id, make_jpeg(), photos_dir)
    session.commit()

    def deny(self, missing_ok=False):
        raise PermissionError("geen rechten")

    monkeypatch.setattr(Path, "unlink", deny)
    vsvc.delete_vehicle(session, a.id, photos_dir)
    session.commit()  # geen uitzondering
    assert session.scalar(select(Vehicle).where(Vehicle.id == a.id)) is None


def test_vehicle_out_toont_geen_bestandsnaam():
    out = VehicleOut.model_json_schema(mode="serialization")["properties"]
    assert "has_photo" in out and "photo_version" not in out and "photo" not in out
