from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from wisselweer.core import DrivingProfile
from wisselweer.storage.db import make_engine, make_session_factory, migrate
from wisselweer.vehicles.schemas import LocationIn, VehicleIn


@pytest.fixture
def db_url(tmp_path):
    url = f"sqlite:///{tmp_path / 'test.db'}"
    migrate(url)
    return url


@pytest.fixture
def engine(db_url):
    eng = make_engine(db_url)
    yield eng
    eng.dispose()


@pytest.fixture
def factory(engine):
    return make_session_factory(engine)


@pytest.fixture
def session(factory):
    s: Session = factory()
    yield s
    s.rollback()
    s.close()


def vehicle_in(name: str = "Testauto", plate: str | None = "XX-000-X", **kw) -> VehicleIn:
    loc = kw.pop("location", LocationIn(name="Utrecht", latitude=52.0907, longitude=5.1214))
    return VehicleIn(
        name=name,
        license_plate=plate,
        location=loc,
        driving_profile=DrivingProfile.commute(),
        **kw,
    )
