from __future__ import annotations

from datetime import date, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import func, select

from tests.integration.api.conftest import MAIL, PLATE, vehicle_body
from wisselweer.api.deps import ensure_db
from wisselweer.storage.orm import (
    AdviceSnapshot,
    Appointment,
    OdometerReading,
    TireChange,
    TireSet,
    Vehicle,
)

API = "/api/v1"
TODAY = date.today()


def _ok(r, status=200):
    assert r.status_code == status, r.text
    return r.json()


def _garage(client, email: str | None = MAIL) -> dict:
    return _ok(client.post(f"{API}/garages", json={"name": "Garage Test", "email": email}), 201)


def _vehicle(client, **kw) -> dict:
    return _ok(client.post(f"{API}/vehicles", json=vehicle_body(**kw)), 201)


def _sets(client, vid: int) -> tuple[dict, dict]:
    summer = _ok(
        client.post(
            f"{API}/vehicles/{vid}/tire-sets", json={"type": "summer", "status": "mounted"}
        ),
        201,
    )
    winter = _ok(client.post(f"{API}/vehicles/{vid}/tire-sets", json={"type": "winter"}), 201)
    return summer, winter


def _change(client, vid: int, set_id: int, when: date, km: int | None = None, **kw):
    body = {"to_set_id": set_id, "changed_at": when.isoformat(), "odometer_km": km, **kw}
    return client.post(f"{API}/vehicles/{vid}/tire-changes", json=body)


def test_full_flow(client, provider):
    garage = _garage(client)
    a = _vehicle(client, change_method="garage", preferred_garage_id=garage["id"], name="Auto A")
    b = _vehicle(client, name="Auto B", plate=None)
    assert a["license_plate"] == PLATE
    assert len(_ok(client.get(f"{API}/vehicles"))) == 2

    summer, winter = _sets(client, a["id"])
    assert [s["id"] for s in _ok(client.get(f"{API}/vehicles/{a['id']}/tire-sets"))] == [
        summer["id"],
        winter["id"],
    ]
    m = _ok(
        client.post(
            f"{API}/tire-sets/{winter['id']}/tread-measurements",
            json={"measured_at": TODAY.isoformat(), "position": "ALL", "depth_mm": 7.5},
        ),
        201,
    )
    assert m["tire_set_id"] == winter["id"]

    # wissel naar winter, en terug naar zomer, daarna weer winter
    c1 = _ok(_change(client, a["id"], winter["id"], TODAY - timedelta(days=30), 10000), 201)
    assert c1["from_set_id"] == summer["id"] and c1["to_set_id"] == winter["id"]
    _ok(_change(client, a["id"], summer["id"], TODAY - timedelta(days=10), 10800), 201)
    c3 = _ok(_change(client, a["id"], winter["id"], TODAY - timedelta(days=1), 10900), 201)
    assert _ok(client.get(f"{API}/vehicles/{a['id']}/tire-changes")) != []
    assert _ok(client.get(f"{API}/tire-sets/{winter['id']}"))["status"] == "mounted"

    km = _ok(client.get(f"{API}/tire-sets/{winter['id']}/km"))
    assert km["intervals"][0]["km"] == 800
    assert c3["odometer_reading_id"] is not None

    readings = _ok(client.get(f"{API}/vehicles/{a['id']}/odometer"))
    assert [r["reading_km"] for r in readings] == [10000, 10800, 10900]
    fixed = _ok(client.post(f"{API}/odometer/{readings[-1]['id']}/correct", json={"new_km": 10950}))
    assert fixed["reading_km"] == 10950
    assert [r["reading_km"] for r in _ok(client.get(f"{API}/vehicles/{a['id']}/odometer"))] == [
        10000,
        10800,
        10950,
    ]

    appt = _ok(
        client.post(
            f"{API}/vehicles/{a['id']}/appointments",
            json={"garage_id": garage["id"], "target_direction": "to_summer"},
        ),
        201,
    )
    assert appt["status"] == "not_planned" and appt["vehicle_id"] == a["id"]
    assert (
        _ok(client.patch(f"{API}/appointments/{appt['id']}", json={"status": "to_request"}))[
            "status"
        ]
        == "to_request"
    )
    assert len(_ok(client.get(f"{API}/vehicles/{a['id']}/appointments"))) == 1
    link = _ok(client.get(f"{API}/appointments/{appt['id']}/mailto"))["mailto"]
    parsed = urlparse(link)
    assert parsed.scheme == "mailto" and parsed.path == MAIL
    assert "Auto A" in parse_qs(parsed.query)["subject"][0]

    # advies: twee voertuigen op dezelfde locatie => één provider-fetch
    adv_a = _ok(client.get(f"{API}/vehicles/{a['id']}/advice"))
    adv_b = _ok(client.get(f"{API}/vehicles/{b['id']}/advice"))
    assert provider.calls == 1
    assert adv_a["advice"]["direction"] and adv_a["source"]["provider"] == "fake"
    assert "plan_appointment_by" in adv_a
    assert adv_a["mailto"] and adv_a["mailto"].startswith(f"mailto:{MAIL}?")
    assert adv_b["mailto"] is None  # zelf wisselen, geen garage

    patched = _ok(client.patch(f"{API}/vehicles/{b['id']}", json={"notes": "n"}))
    assert patched["notes"] == "n" and patched["name"] == "Auto B"


def test_garage_crud_and_conflict(client):
    g = _garage(client)
    assert _ok(client.patch(f"{API}/garages/{g['id']}", json={"phone": "000"}))["phone"] == "000"
    assert len(_ok(client.get(f"{API}/garages"))) == 1
    v = _vehicle(client)
    _ok(
        client.post(
            f"{API}/vehicles/{v['id']}/appointments",
            json={"garage_id": g["id"], "target_direction": "to_winter"},
        ),
        201,
    )
    r = client.delete(f"{API}/garages/{g['id']}")
    assert r.status_code == 409 and r.json()["detail"] == "invalid_operation"
    g2 = _garage(client)
    assert client.delete(f"{API}/garages/{g2['id']}").status_code == 204


def test_mailto_without_garage_email_is_409(client):
    g = _garage(client, email=None)
    v = _vehicle(client)
    appt = _ok(
        client.post(
            f"{API}/vehicles/{v['id']}/appointments",
            json={"garage_id": g["id"], "target_direction": "to_winter"},
        ),
        201,
    )
    r = client.get(f"{API}/appointments/{appt['id']}/mailto")
    assert r.status_code == 409
    assert r.json()["reason"]


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/vehicles/999"),
        ("patch", "/vehicles/999"),
        ("delete", "/vehicles/999"),
        ("get", "/vehicles/999/advice"),
        ("get", "/vehicles/999/tire-sets"),
        ("get", "/vehicles/999/tire-changes"),
        ("get", "/vehicles/999/odometer"),
        ("get", "/vehicles/999/appointments"),
        ("get", "/tire-sets/999"),
        ("get", "/tire-sets/999/km"),
        ("delete", "/tire-sets/999"),
        ("get", "/garages/999"),
        ("delete", "/garages/999"),
        ("get", "/appointments/999/mailto"),
    ],
)
def test_not_found(client, method, path):
    kwargs = {"json": {}} if method == "patch" else {}
    r = getattr(client, method)(f"{API}{path}", **kwargs)
    assert r.status_code == 404, r.text
    assert r.json() == {"detail": "not_found"}


def test_not_found_on_bodies(client):
    assert client.post(f"{API}/odometer/999/correct", json={"new_km": 1}).status_code == 404
    assert client.patch(f"{API}/appointments/999", json={"status": "to_request"}).status_code == 404
    assert client.post(f"{API}/vehicles/999/tire-sets", json={"type": "winter"}).status_code == 404


def test_conflicts(client):
    v = _vehicle(client)
    summer, winter = _sets(client, v["id"])

    # tweede gemonteerde set
    r = client.post(
        f"{API}/vehicles/{v['id']}/tire-sets", json={"type": "winter", "status": "mounted"}
    )
    assert r.status_code == 409 and r.json()["detail"] == "invalid_operation"
    # al gemonteerde set opnieuw monteren
    assert _change(client, v["id"], summer["id"], TODAY).status_code == 409
    # monteren via PATCH mag niet
    assert (
        client.patch(f"{API}/tire-sets/{winter['id']}", json={"status": "mounted"}).status_code
        == 409
    )

    # lagere km dan bestaande stand
    _ok(_change(client, v["id"], winter["id"], TODAY - timedelta(days=5), 20000), 201)
    r = _change(client, v["id"], summer["id"], TODAY - timedelta(days=2), 19000)
    assert r.status_code == 409 and "kilometerstand" in r.json()["reason"]
    # mislukte wissel laat niets achter
    assert _ok(client.get(f"{API}/tire-sets/{winter['id']}"))["status"] == "mounted"
    assert len(_ok(client.get(f"{API}/vehicles/{v['id']}/tire-changes"))) == 1

    # ongeldige statusovergang afspraak
    g = _garage(client)
    appt = _ok(
        client.post(
            f"{API}/vehicles/{v['id']}/appointments",
            json={"garage_id": g["id"], "target_direction": "to_winter"},
        ),
        201,
    )
    r = client.patch(f"{API}/appointments/{appt['id']}", json={"status": "done"})
    assert r.status_code == 409 and r.json()["detail"] == "invalid_operation"

    # set in wisselhistorie kan niet verwijderd worden; ongebruikte wel
    assert client.delete(f"{API}/tire-sets/{summer['id']}").status_code == 409
    extra = _ok(
        client.post(f"{API}/vehicles/{v['id']}/tire-sets", json={"type": "all_season"}), 201
    )
    assert client.delete(f"{API}/tire-sets/{extra['id']}").status_code == 204

    # corrigeren van een al gecorrigeerde stand
    rid = _ok(client.get(f"{API}/vehicles/{v['id']}/odometer"))[0]["id"]
    _ok(client.post(f"{API}/odometer/{rid}/correct", json={"new_km": 20001}))
    assert client.post(f"{API}/odometer/{rid}/correct", json={"new_km": 20002}).status_code == 409


@pytest.mark.parametrize(
    "path,body",
    [
        (
            "/vehicles",
            {**vehicle_body(), "location": {"name": "X", "latitude": 91, "longitude": 5}},
        ),
        (
            "/vehicles",
            {**vehicle_body(), "location": {"name": "X", "latitude": 5, "longitude": 181}},
        ),
        ("/vehicles", {**vehicle_body(), "timezone": "Mars/Olympus"}),
        ("/garages", {"name": "", "email": MAIL}),
    ],
)
def test_validation_422_no_echo(client, path, body):
    r = client.post(f"{API}{path}", json=body)
    assert r.status_code == 422
    assert r.json()["detail"] == "validation_error"
    assert PLATE not in r.text and MAIL not in r.text


def test_validation_tires(client):
    v = _vehicle(client)
    _, winter = _sets(client, v["id"])
    assert (
        client.post(f"{API}/vehicles/{v['id']}/tire-sets", json={"type": "slicks"}).status_code
        == 422
    )
    assert _change(client, v["id"], winter["id"], TODAY, -1).status_code == 422
    assert client.post(f"{API}/odometer/1/correct", json={"new_km": -5}).status_code == 422
    assert (
        client.post(
            f"{API}/tire-sets/{winter['id']}/tread-measurements",
            json={"measured_at": TODAY.isoformat(), "position": "XX", "depth_mm": 5},
        ).status_code
        == 422
    )
    assert client.get(f"{API}/vehicles/abc").status_code == 422


def test_no_pii_in_error_responses(client):
    v = _vehicle(client)
    responses = [
        client.get(f"{API}/vehicles/999"),
        client.post(f"{API}/vehicles/{v['id']}/tire-sets", json={"type": "slicks", "notes": PLATE}),
        client.post(f"{API}/vehicles", json={**vehicle_body(), "build_year": 1}),
        client.patch(f"{API}/appointments/999", json={"status": "to_request"}),
        client.post(
            f"{API}/vehicles/{v['id']}/appointments",
            json={"garage_id": 999, "target_direction": "to_winter"},
        ),
    ]
    for r in responses:
        assert r.status_code >= 400
        assert PLATE not in r.text and MAIL not in r.text and "Traceback" not in r.text


def test_delete_vehicle_cascades(client, app):
    g = _garage(client)
    v = _vehicle(client)
    other = _vehicle(client, name="Andere", plate=None)
    summer, winter = _sets(client, v["id"])
    _sets(client, other["id"])
    _ok(_change(client, v["id"], winter["id"], TODAY - timedelta(days=3), 5000), 201)
    _ok(
        client.post(
            f"{API}/vehicles/{v['id']}/appointments",
            json={"garage_id": g["id"], "target_direction": "to_summer"},
        ),
        201,
    )
    _ok(client.get(f"{API}/vehicles/{v['id']}/advice"))

    assert client.delete(f"{API}/vehicles/{v['id']}").status_code == 204
    assert client.get(f"{API}/vehicles/{v['id']}").status_code == 404
    assert client.get(f"{API}/tire-sets/{summer['id']}").status_code == 404

    factory = ensure_db(app)
    with factory() as s:
        for model in (TireSet, TireChange, OdometerReading, Appointment, AdviceSnapshot):
            n = s.scalar(
                select(func.count()).select_from(model).where(model.vehicle_id == v["id"])
                if hasattr(model, "vehicle_id")
                else select(func.count()).select_from(model)
            )
            if model is TireSet:
                n = s.scalar(
                    select(func.count()).select_from(TireSet).where(TireSet.vehicle_id == v["id"])
                )
            assert n == 0, model.__name__
        assert s.scalar(select(func.count()).select_from(Vehicle)) == 1
        assert (
            s.scalar(
                select(func.count()).select_from(TireSet).where(TireSet.vehicle_id == other["id"])
            )
            == 2
        )
    assert client.get(f"{API}/vehicles/{other['id']}").status_code == 200


def test_existing_routes_still_work(client):
    assert _ok(client.get(f"{API}/health"))["status"] == "ok"
    r = client.get(f"{API}/advice", params={"mounted": "summer", "latitude": 52, "longitude": 5})
    assert r.status_code == 200, r.text
    assert "fake" in {p["id"] for p in _ok(client.get(f"{API}/providers"))["providers"]}


def test_manual_odometer_reading(client):
    v = _vehicle(client)
    body = {"reading_km": 12345, "note": "handmatig"}
    r = _ok(client.post(f"{API}/vehicles/{v['id']}/odometer", json=body), 201)
    assert r["reading_km"] == 12345 and r["source"] == "manual"
    listed = _ok(client.get(f"{API}/vehicles/{v['id']}/odometer"))
    assert [x["reading_km"] for x in listed] == [12345]
    lower = {"reading_km": 100, "recorded_at": "2099-01-01T00:00:00Z"}
    assert client.post(f"{API}/vehicles/{v['id']}/odometer", json=lower).status_code == 409
    assert client.post(f"{API}/vehicles/9999/odometer", json=body).status_code == 404
