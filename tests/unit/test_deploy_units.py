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
    # De publicatieservice heeft de sleutel wel nodig, dus die mag hem niet verbergen.
    assert "InaccessiblePaths=-/var/lib/wisselweer/.ssh" not in _regels(
        "wisselweer-publish.service"
    )


def test_publicatieservice_ziet_de_voertuigfotos_niet():
    assert "InaccessiblePaths=-/var/lib/wisselweer/photos" in _regels("wisselweer-publish.service")
    # De webapp serveert de foto's en moet erbij kunnen.
    webapp = _regels("wisselweer.service")
    assert not any("photos" in r for r in webapp if r.startswith("InaccessiblePaths="))
    assert "ReadWritePaths=/var/lib/wisselweer" in webapp


def test_update_script_maakt_fotoback_up():
    import subprocess

    script = DEPLOY / "update.sh"
    assert subprocess.run(["bash", "-n", str(script)]).returncode == 0
    text = script.read_text()
    for needle in (
        'if [[ -d "$DATA_DIR/photos" ]]; then',
        'tar -C "$DATA_DIR" -czf "$BACKUP_DIR/wisselweer-$STAMP-photos.tar.gz" photos',
        'chmod 0600 "$BACKUP_DIR/wisselweer-$STAMP-photos.tar.gz"',
    ):
        assert needle in text, needle
    # De foto-back-up gebeurt vóór de installatie van de nieuwe code.
    assert text.index("photos.tar.gz") < text.index('"$HERE/install.sh"')


def test_cli_wrapper_runs_as_service_user_with_env_file():
    import subprocess

    wrapper = DEPLOY / "wisselweer-cli.sh"
    text = wrapper.read_text()
    assert subprocess.run(["sh", "-n", str(wrapper)]).returncode == 0
    for needle in (
        "-p User=wisselweer",
        "-p EnvironmentFile=/etc/wisselweer/wisselweer.env",
        '/opt/wisselweer/.venv/bin/wisselweer "$@"',
        "--wait",
    ):
        assert needle in text, needle
    install = (DEPLOY / "install.sh").read_text()
    assert 'wisselweer-cli.sh" /usr/local/bin/wisselweer' in install
