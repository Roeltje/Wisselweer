"""Demping van het landelijke advies (regio's via `previous`, landelijke status via helper)."""

from __future__ import annotations

import json
import os
import stat
from datetime import timedelta

import pytest

from tests.unit.publisher.helpers import COLD, MILD, NAMES, NOW, FakeForecasts, fc, uniform
from wisselweer.publisher.national import NationalAdviceService
from wisselweer.publisher.national_stability import (
    NationalHold,
    dampen_national_status,
    load_state,
)
from wisselweer.publisher.public_schema import PublicPeriod

R1 = NOW
R2 = NOW + timedelta(hours=6)
R3 = NOW + timedelta(hours=12)


def svc(forecasts, path, persist=True):
    return NationalAdviceService(forecasts, state_path=path, persist=persist)


# ----------------------------------------------------------------- helper (puur)


def hold(status, raw=None, streak=0, season="winter"):
    return NationalHold(season=season, status=status, raw_status=raw or status, streak=streak)


def damp(raw, previous, season="winter", n=2):
    return dampen_national_status(raw, season, previous, n)


def test_no_previous_is_direct():
    d = damp("KEEP_CURRENT", None)
    assert (d.status, d.held) == ("KEEP_CURRENT", False)


def test_winter_upward_is_direct():
    assert damp("PREPARE_CHANGE", hold("KEEP_CURRENT")).held is False
    d = damp("CHANGE_RECOMMENDED", hold("KEEP_CURRENT"))
    assert (d.status, d.held) == ("CHANGE_RECOMMENDED", False)


def test_winter_downward_needs_two():
    first = damp("KEEP_CURRENT", hold("CHANGE_RECOMMENDED"))
    assert (first.status, first.held, first.streak, first.raw_status) == (
        "CHANGE_RECOMMENDED",
        True,
        1,
        "KEEP_CURRENT",
    )
    second = damp("KEEP_CURRENT", hold("CHANGE_RECOMMENDED", raw="KEEP_CURRENT", streak=1))
    assert (second.status, second.held) == ("KEEP_CURRENT", False)


def test_different_raw_status_restarts_streak():
    d = damp("PREPARE_CHANGE", hold("CHANGE_RECOMMENDED", raw="KEEP_CURRENT", streak=1))
    assert (d.status, d.held, d.streak) == ("CHANGE_RECOMMENDED", True, 1)


def test_regional_differences_flip_needs_two_both_ways():
    assert damp("REGIONAL_DIFFERENCES", hold("CHANGE_RECOMMENDED")).held is True
    assert damp("CHANGE_RECOMMENDED", hold("REGIONAL_DIFFERENCES")).held is True
    d = damp(
        "REGIONAL_DIFFERENCES", hold("CHANGE_RECOMMENDED", raw="REGIONAL_DIFFERENCES", streak=1)
    )
    assert (d.status, d.held) == ("REGIONAL_DIFFERENCES", False)


def test_insufficient_data_is_always_direct():
    assert damp("INSUFFICIENT_DATA", hold("CHANGE_RECOMMENDED")).held is False
    d = damp("KEEP_CURRENT", hold("INSUFFICIENT_DATA"))
    assert (d.status, d.held) == ("KEEP_CURRENT", False)


def test_summer_upward_also_needs_two():
    assert damp("CHANGE_RECOMMENDED", hold("KEEP_CURRENT", season="summer"), "summer").held is True


def test_other_season_previous_is_ignored():
    assert damp("KEEP_CURRENT", hold("CHANGE_RECOMMENDED", season="summer")).held is False


def test_confirmations_come_from_parameter():
    assert damp("KEEP_CURRENT", hold("CHANGE_RECOMMENDED"), n=1).held is False


# ----------------------------------------------------------------- service + state


def test_without_state_path_nothing_is_damped(tmp_path):
    a = NationalAdviceService(uniform(COLD)).compute(R1)
    b = NationalAdviceService(uniform(MILD)).compute(R2)
    assert (a.status, b.status) == ("CHANGE_RECOMMENDED", "KEEP_CURRENT")


def test_regions_and_national_are_held_then_confirmed(tmp_path):
    path = tmp_path / "national_state.json"
    first = svc(uniform(COLD), path).compute(R1)
    assert first.status == "CHANGE_RECOMMENDED"

    second = svc(uniform(MILD), path).compute(R2)  # 1e afwijkende berekening
    assert second.status == "CHANGE_RECOMMENDED"
    assert second.status_label == first.status_label
    # Samenvatting van de vastgehouden status; de waarschuwingsnotitie volgt de nieuwe berekening.
    assert second.summary.startswith("Volgens de verwachting is het")
    assert second.summary in first.summary
    assert second.recommended_date == first.recommended_date
    assert {r.status for r in second.regions} == {"CHANGE_RECOMMENDED"}

    # Regio's bevestigen de daling nu (2e keer); het landelijke niveau telt die als 1e afwijking.
    third = svc(uniform(MILD), path).compute(R3)
    assert {r.status for r in third.regions} == {"KEEP_CURRENT"}
    assert third.status == "CHANGE_RECOMMENDED"

    fourth = svc(uniform(MILD), path).compute(NOW + timedelta(hours=18))
    assert fourth.status == "KEEP_CURRENT"
    assert fourth.recommended_date is None


def test_flapping_input_does_not_flip_advice(tmp_path):
    path = tmp_path / "s.json"
    statuses = []
    for i, days in enumerate([COLD, MILD, COLD, MILD, COLD]):
        statuses.append(svc(uniform(days), path).compute(NOW + timedelta(hours=6 * i)).status)
    assert set(statuses) == {"CHANGE_RECOMMENDED"}


def test_winter_upward_is_immediate_through_service(tmp_path):
    path = tmp_path / "s.json"
    assert svc(uniform(MILD), path).compute(R1).status == "KEEP_CURRENT"
    assert svc(uniform(COLD), path).compute(R2).status == "CHANGE_RECOMMENDED"


def test_one_region_dropping_is_held_by_region_hysteresis(tmp_path):
    path = tmp_path / "s.json"
    svc(uniform(COLD), path).compute(R1)
    by = {NAMES[0]: fc(MILD)} | {n: fc(COLD) for n in NAMES[1:]}
    b = svc(FakeForecasts(by), path).compute(R2)
    assert b.regional_variation is False  # De Bilt blijft (nog) CHANGE_RECOMMENDED
    assert {r.status for r in b.regions} == {"CHANGE_RECOMMENDED"}


def test_state_file_written_atomically_with_content(tmp_path):
    path = tmp_path / "data" / "national_state.json"
    a = svc(uniform(COLD), path).compute(R1)
    assert not list(path.parent.glob("*.tmp"))
    assert stat.S_IMODE(os.stat(path).st_mode) in (0o600, 0o640)
    data = json.loads(path.read_text())
    assert set(data) == {"regions", "national", "generated_at"}
    assert set(data["regions"]) == set(NAMES)
    assert data["national"]["status"] == a.status
    assert data["national"]["season"] == "winter"
    assert set(data["national"]) == {
        "season",
        "status",
        "raw_status",
        "streak",
        "recommended_date",
        "recommended_period",
    }


def test_persist_false_reads_but_never_writes(tmp_path):
    path = tmp_path / "s.json"
    assert not svc(uniform(COLD), path, persist=False).compute(R1).status == "x"
    assert not path.exists()
    svc(uniform(COLD), path).compute(R1)
    before = path.read_text()
    held = svc(uniform(MILD), path, persist=False).compute(R2)
    assert held.status == "CHANGE_RECOMMENDED"  # leest de staat wel
    assert path.read_text() == before


def _set(path, **changes):
    data = json.loads(path.read_text())
    for k, v in changes.items():
        if k == "season":
            data["national"]["season"] = v
        else:
            data[k] = v
    path.write_text(json.dumps(data))


@pytest.mark.parametrize("kind", ["season", "old", "corrupt", "garbage_json"])
def test_unusable_state_is_ignored(tmp_path, kind, caplog):
    path = tmp_path / "s.json"
    svc(uniform(COLD), path).compute(R1)
    if kind == "season":
        _set(path, season="summer")
    elif kind == "old":
        _set(path, generated_at=(NOW - timedelta(hours=60)).isoformat())
    elif kind == "corrupt":
        path.write_text("{ niet json")
    else:
        path.write_text('{"regions": 3}')
    b = svc(uniform(MILD), path).compute(R2)
    assert b.status == "KEEP_CURRENT"  # niet vastgehouden
    if kind in ("corrupt", "garbage_json"):
        assert "national_state_unreadable" in caplog.text


def test_load_state_missing_file_is_none(tmp_path):
    assert load_state(tmp_path / "nope.json", NOW, "winter") is None
    assert load_state(None, NOW, "winter") is None


def test_unwritable_state_path_does_not_break_compute(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    a = svc(uniform(COLD), blocker / "sub" / "s.json").compute(R1)
    assert a.status == "CHANGE_RECOMMENDED"


def test_held_period_is_kept():
    h = NationalHold(
        season="winter",
        status="PREPARE_CHANGE",
        raw_status="PREPARE_CHANGE",
        recommended_period=PublicPeriod(start="2026-11-10", end="2026-11-13"),
    )
    assert h.recommended_period.end.isoformat() == "2026-11-13"
