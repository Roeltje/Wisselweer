"""deploy/docker-install.sh: draait met een nep-`docker` en nep-`curl` die hun aanroepen loggen.

De echte Docker-test (image bouwen, starten, update-pad) staat in de CI-job `docker`.
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "deploy" / "docker-install.sh"
ENV_EXAMPLE = ROOT / ".env.example"
CONTACT = "https://example.invalid/mijn-garage"

NEP_DOCKER = """#!/bin/sh
line=$(printf 'docker %s' "$*" | tr '\\n' ' ')
echo "$line" >> "$STUB_LOG"
case "$*" in
  "compose version --short") echo "${STUB_COMPOSE_VERSION:-2.29.1}" ;;
  *"ps -q publisher"*) [ -z "${STUB_PUBLISHER:-}" ] || echo pub123 ;;
  *"ps -q wisselweer"*) echo wwid ;;
  inspect*) echo "${STUB_STATE:-running healthy}" ;;
  *"run "*"python -c"*) printf 'SQLITE-BACKUP'; exit "${STUB_DB_RC:-0}" ;;
  *"run "*"test -d"*) [ -z "${STUB_NO_PHOTOS:-}" ] || exit 1 ;;
  *"run "*"tar "*) printf 'TARDATA' ;;
esac
exit 0
"""

NEP_CURL = """#!/bin/sh
echo "curl $*" >> "$STUB_LOG"
[ -z "${STUB_CURL_FAIL:-}" ] || exit 22
out=""; url=""
while [ $# -gt 0 ]; do
  case "$1" in -o) out="$2"; shift ;; http*) url="$1" ;; esac
  shift
done
case "$url" in
  */compose.yaml) printf 'services:\\n  wisselweer:\\n    image: ghcr.io/roeltje/wisselweer:x\\n' > "$out" ;;
  */env.example) cp "$ENV_EXAMPLE_SRC" "$out" ;;
  *) exit 22 ;;
esac
"""


@pytest.fixture
def stubs(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for naam, tekst in (("docker", NEP_DOCKER), ("curl", NEP_CURL)):
        (bindir / naam).write_text(tekst)
        (bindir / naam).chmod(0o755)
    return bindir


@pytest.fixture
def run(tmp_path, stubs):
    log = tmp_path / "stub.log"
    log.write_text("")
    target = tmp_path / "ww"

    def _run(*args, env=None, directory=target, with_contact=True):
        full_env = {
            **os.environ,
            "PATH": f"{stubs}{os.pathsep}{os.environ['PATH']}",
            "STUB_LOG": str(log),
            "ENV_EXAMPLE_SRC": str(ENV_EXAMPLE),
            "WISSELWEER_HEALTH_TIMEOUT": "2",
        }
        for var in ("WISSELWEER_CONTACT", "WISSELWEER_ASSETS_DIR", "IMAGE_TAG", "COMPOSE_PROFILES"):
            full_env.pop(var, None)
        if with_contact:
            full_env["WISSELWEER_CONTACT"] = CONTACT
        full_env.update(env or {})
        cmd = ["bash", str(SCRIPT), *args]
        if directory is not None:
            cmd.append(str(directory))
        return subprocess.run(
            cmd,
            env=full_env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=60,
        )

    _run.log = lambda: log.read_text().splitlines()
    _run.dir = target
    return _run


def _index(regels: list[str], begin: str) -> int:
    for i, r in enumerate(regels):
        if r.startswith(begin):
            return i
    raise AssertionError(f"{begin!r} niet gelogd: {regels}")


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_bash_syntax_en_uitvoerbaar():
    assert subprocess.run(["bash", "-n", str(SCRIPT)]).returncode == 0
    assert _mode(SCRIPT) & 0o111
    assert "set -euo pipefail" in SCRIPT.read_text()


def test_help_en_ongeldige_argumenten(run):
    r = run("--help", directory=None)
    assert r.returncode == 0 and "Gebruik: bash docker-install.sh" in r.stdout
    assert run("--version", "1.2", directory=None).returncode == 1
    r = run("--onbekend", directory=None)
    assert r.returncode == 1 and "Onbekende optie" in r.stderr
    assert run.log() == []  # niets aangeroepen voor de argumentcontrole


def test_nieuwe_installatie_maakt_env_met_secret_en_start(run):
    r = run()
    assert r.returncode == 0, r.stderr
    env_file = run.dir / ".env"
    assert _mode(env_file) == 0o600
    regels = env_file.read_text().splitlines()
    secret = next(x for x in regels if x.startswith("WISSELWEER_SECRET_KEY=")).split("=", 1)[1]
    assert len(secret) >= 48 and re.fullmatch(r"[A-Za-z0-9_-]+", secret)
    assert f"WISSELWEER_CONTACT={CONTACT}" in regels
    # Alleen die twee regels verschillen van het voorbeeld.
    voorbeeld = ENV_EXAMPLE.read_text().splitlines()
    verschil = [(a, b) for a, b in zip(voorbeeld, regels, strict=True) if a != b]
    assert len(verschil) == 2 and len(voorbeeld) == len(regels)
    assert (run.dir / "compose.yaml").read_text().startswith("services:")
    assert (run.dir / ".env.example").exists()
    assert not list(run.dir.glob(".installer.*"))  # tijdelijke map opgeruimd
    # Geen back-up bij een eerste installatie; wel pull, up en wachten op gezond.
    log = run.log()
    assert not any(" run " in x for x in log) and not (run.dir / "backups").exists()
    assert _index(log, "docker compose pull") < _index(log, "docker compose up -d")
    assert _index(log, "docker compose up -d") < _index(log, "docker inspect")
    assert "create-admin --username <naam>" in r.stdout
    assert "geen poort of firewall" in r.stdout
    assert secret not in r.stdout + r.stderr  # sleutel wordt niet getoond


def test_downloads_gaan_via_https_van_de_nieuwste_release(run):
    assert run().returncode == 0
    curls = [x for x in run.log() if x.startswith("curl ")]
    assert len(curls) == 2
    for x in curls:
        assert "--proto =https" in x and "--tlsv1.2" in x and "-fsSL" in x
    assert any(
        x.endswith("https://github.com/Roeltje/Wisselweer/releases/latest/download/compose.yaml")
        for x in curls
    )
    assert any(x.endswith("/releases/latest/download/env.example") for x in curls)


def test_vaste_versie_downloadt_van_die_release(run):
    assert run("--version", "v0.1.0").returncode == 0
    assert any("/releases/download/v0.1.0/compose.yaml" in x for x in run.log())


def test_assets_dir_voorkomt_downloads_en_skip_pull_slaat_pull_over(run, tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "compose.yaml").write_text("services:\n  wisselweer: {}\n")
    (assets / ".env.example").write_text(ENV_EXAMPLE.read_text())  # punt-variant is ook goed
    env = {
        "WISSELWEER_ASSETS_DIR": str(assets),
        "IMAGE_TAG": "ci",
        "WISSELWEER_SKIP_PULL": "1",
    }
    r = run(env=env)
    assert r.returncode == 0, r.stderr
    log = run.log()
    assert not any(x.startswith("curl") for x in log)
    assert not any(x.startswith("docker compose pull") for x in log)
    assert "docker compose up -d" in log
    assert (run.dir / "compose.yaml").read_text().startswith("services:")


def test_assets_dir_zonder_compose_faalt(run, tmp_path):
    (tmp_path / "leeg").mkdir()
    r = run(env={"WISSELWEER_ASSETS_DIR": str(tmp_path / "leeg")})
    assert r.returncode == 1 and "Ontbreekt in WISSELWEER_ASSETS_DIR" in r.stderr
    assert not (run.dir / ".env").exists()


def test_contact_is_verplicht_zonder_terminal(run):
    r = run(with_contact=False)
    assert r.returncode == 1 and "WISSELWEER_CONTACT is verplicht" in r.stderr
    assert not (run.dir / ".env").exists() and not (run.dir / "compose.yaml").exists()
    assert not any(x.startswith("docker compose up") for x in run.log())


@pytest.mark.parametrize("contact", ["met spatie", "a$b", "x'y", "a#b", "x\\y"])
def test_onveilig_contactgegeven_wordt_geweigerd(run, contact):
    r = run(env={"WISSELWEER_CONTACT": contact})
    assert r.returncode == 1 and "contactgegeven" in r.stderr
    assert not (run.dir / ".env").exists()


def test_downloadfout_laat_de_map_ongemoeid(run):
    r = run(env={"STUB_CURL_FAIL": "1"})
    assert r.returncode == 1 and "Downloaden mislukt" in r.stderr
    assert not (run.dir / ".env").exists() and not (run.dir / "compose.yaml").exists()
    assert not any(x.startswith("docker compose") and "version" not in x for x in run.log())


def test_oude_compose_wordt_geweigerd(run):
    r = run(env={"STUB_COMPOSE_VERSION": "1.29.2"})
    assert r.returncode == 1 and "Compose v2" in r.stderr


def _bestaande_installatie(directory: Path) -> bytes:
    directory.mkdir()
    (directory / "compose.yaml").write_text("services:\n  oud: {}\n")
    inhoud = b"WISSELWEER_SECRET_KEY=bestaand-geheim\n# eigen regel\nWISSELWEER_CONTACT=mij\n"
    (directory / ".env").write_bytes(inhoud)
    (directory / ".env").chmod(0o600)
    return inhoud


def test_update_laat_bestaand_env_ongemoeid_en_maakt_eerst_een_backup(run):
    inhoud = _bestaande_installatie(run.dir)
    r = run(with_contact=False)  # contact is niet nodig: .env bestaat al
    assert r.returncode == 0, r.stderr
    assert (run.dir / ".env").read_bytes() == inhoud
    assert _mode(run.dir / ".env") == 0o600
    backups = run.dir / "backups"
    assert _mode(backups) == 0o700
    db = next(backups.glob("wisselweer-*.db"))
    assert db.read_bytes() == b"SQLITE-BACKUP" and _mode(db) == 0o600
    foto = next(backups.glob("wisselweer-*-photos.tar.gz"))
    assert foto.read_bytes() == b"TARDATA" and _mode(foto) == 0o600
    assert "services:\n  oud: {}" in next(backups.glob("compose-*.yaml")).read_text()
    # Nieuwe compose staat er, en de back-up gebeurde vóór pull en up.
    assert "wisselweer:" in (run.dir / "compose.yaml").read_text()
    log = run.log()
    back_up = _index(log, "docker compose run --rm --no-deps -T wisselweer python -c")
    assert back_up < _index(log, "docker compose pull") < _index(log, "docker compose up -d")
    assert "Bijgewerkt" in r.stdout and "create-admin" not in r.stdout


def test_update_zonder_foto_s_of_database(run):
    _bestaande_installatie(run.dir)
    r = run(env={"STUB_NO_PHOTOS": "1", "STUB_DB_RC": "3"})
    assert r.returncode == 0, r.stderr
    assert not list((run.dir / "backups").glob("wisselweer-*"))
    assert "Nog geen database" in r.stdout


def test_update_stopt_als_de_backup_mislukt(run):
    _bestaande_installatie(run.dir)
    r = run(env={"STUB_DB_RC": "1"})
    assert r.returncode == 1 and "Back-up van de database mislukt" in r.stderr
    assert (run.dir / "compose.yaml").read_text() == "services:\n  oud: {}\n"  # niets vervangen
    assert not list((run.dir / "backups").glob("wisselweer-*"))
    log = run.log()
    assert not any(x.startswith(("docker compose pull", "docker compose up")) for x in log)


def test_update_neemt_een_draaiende_publisher_mee(run):
    _bestaande_installatie(run.dir)
    r = run(env={"STUB_PUBLISHER": "1"})
    assert r.returncode == 0 and "Publisher-container gevonden" in r.stdout


def test_ongezonde_container_geeft_logs_en_exitcode_1(run):
    r = run(env={"STUB_STATE": "running starting"})
    assert r.returncode == 1 and "werd niet gezond" in r.stderr
    assert any(x.startswith("docker compose logs") for x in run.log())
