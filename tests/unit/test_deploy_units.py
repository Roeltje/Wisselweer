"""Systemd-units in deploy/: hardening-regels blijven aanwezig (geen vervanging van systemd-analyze)."""

from __future__ import annotations

from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parents[2] / "deploy"
UNITS = ["wisselweer.service", "wisselweer-publish.service"]

VERPLICHT = [
    "NoNewPrivileges=true",
    "ProtectSystem=strict",
    "ProtectProc=invisible",
    "ProcSubset=pid",
    "RemoveIPC=true",
    "TasksMax=128",
    "MemoryMax=512M",
    "SystemCallArchitectures=native",
    "SystemCallFilter=@system-service",
    "SystemCallFilter=~@privileged @resources",
    "LockPersonality=true",
    "RestrictRealtime=true",
    "RestrictSUIDSGID=true",
    "ProtectHostname=true",
    "ProtectClock=true",
    "ProtectKernelLogs=true",
]


def _regels(unit: str) -> list[str]:
    tekst = (DEPLOY / unit).read_text(encoding="utf-8")
    return [r.strip() for r in tekst.splitlines() if r.strip() and not r.startswith("#")]


@pytest.mark.parametrize("unit", UNITS)
def test_hardening_aanwezig(unit):
    regels = _regels(unit)
    for r in VERPLICHT:
        assert r in regels, (unit, r)
    # Bewust niet: risico in LXC/CPython.
    assert not any(r.startswith(("PrivateUsers=", "MemoryDenyWriteExecute=")) for r in regels)


def test_webapp_kan_sftp_sleutel_niet_lezen():
    assert "InaccessiblePaths=-/var/lib/wisselweer/.ssh" in _regels("wisselweer.service")
    assert not any(
        r.startswith("InaccessiblePaths=") for r in _regels("wisselweer-publish.service")
    )
