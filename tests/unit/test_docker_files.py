"""Docker-bestanden: compose.yaml, compose.build.yaml en de workflows houden hun afspraken.

Geen vervanging van een echte build: die draait in de CI-job `docker`. De tekstchecks werken
zonder extra dependency; de structurele checks draaien alleen als PyYAML beschikbaar is.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "compose.yaml"
BUILD = ROOT / "compose.build.yaml"
WORKFLOWS = ROOT / ".github" / "workflows"
IMAGE = "ghcr.io/roeltje/wisselweer"
SERVICES = ["wisselweer", "publisher"]


def _blokken(pad: Path) -> dict[str, list[str]]:
    """Regels (zonder commentaar en lege regels) per service onder `services:`."""
    blokken: dict[str, list[str]] = {}
    huidig: str | None = None
    in_services = False
    for regel in pad.read_text(encoding="utf-8").splitlines():
        if re.match(r"^services:\s*$", regel):
            in_services = True
            continue
        if re.match(r"^\S", regel) and not regel.startswith("#"):
            in_services = False
            huidig = None
        if not in_services:
            continue
        m = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", regel)
        if m:
            huidig = m.group(1)
            blokken[huidig] = []
        elif huidig and regel.strip() and not regel.strip().startswith("#"):
            blokken[huidig].append(regel.strip())
    return blokken


@pytest.fixture(scope="module")
def compose() -> dict[str, list[str]]:
    return _blokken(COMPOSE)


def test_services_zijn_gevonden(compose):
    assert set(compose) == set(SERVICES)


@pytest.mark.parametrize("service", SERVICES)
def test_hardening_blijft_aanwezig(compose, service):
    regels = compose[service]
    for verplicht in (
        "read_only: true",
        "- ALL",
        "cap_drop:",
        "- no-new-privileges:true",
        "- /tmp",
        "- wisselweer-data:/data",
        "restart: unless-stopped",
    ):
        assert verplicht in regels, (service, verplicht)


def test_webapp_alleen_op_localhost_en_zonder_build(compose):
    regels = compose["wisselweer"]
    assert '- "127.0.0.1:8000:8000"' in regels
    assert [r for r in regels if re.match(r'^- "?\d+[.:]', r)] == ['- "127.0.0.1:8000:8000"']
    assert not any(r.startswith("build:") for r in regels)
    assert "container_name: wisselweer" in regels
    assert "profiles: [publish]" not in regels  # de webapp start altijd


def test_image_komt_van_ghcr_voor_beide_services(compose):
    for service in SERVICES:
        assert f"image: {IMAGE}:${{IMAGE_TAG:-latest}}" in compose[service], service
    assert "build:" not in COMPOSE.read_text()
    # Release-workflow vervangt precies deze tekst door de versie.
    assert COMPOSE.read_text().count(":${IMAGE_TAG:-latest}") == 2


def test_webapp_krijgt_geen_sftp_sleutel_of_secrets(compose):
    for regel in compose["wisselweer"]:
        assert "secrets" not in regel, regel
        assert "deploy_key" not in regel and "known_hosts" not in regel, regel
    assert "- wisselweer-data:/data" in compose["wisselweer"]


def test_publisher_heeft_profiel_en_alleen_hier_staan_de_secrets(compose):
    regels = compose["publisher"]
    assert "profiles: [publish]" in regels
    assert "source: ./secrets" in regels and "target: /run/secrets" in regels
    assert "create_host_path: false" in regels  # geen lege, root-eigen map aanmaken
    assert regels.count("read_only: true") == 2  # root-fs én de bind-mount
    assert "ports:" not in regels  # geen poort naar de host
    command = next(r for r in regels if r.startswith("command:"))
    assert "publish" in command and "--every-hours" in command
    # De HEALTHCHECK van het image test de webserver, die hier niet draait.
    assert "healthcheck:" in regels and "disable: true" in regels


def test_compose_build_override():
    regels = _blokken(BUILD)
    assert "build: ." in regels["wisselweer"] and "image: wisselweer:local" in regels["wisselweer"]
    assert "image: wisselweer:local" in regels["publisher"]
    assert not any(r.startswith("build:") for r in regels["publisher"])
    for service in SERVICES:
        assert "pull_policy: never" in regels[service]


def test_dockerignore_houdt_geheimen_en_buildbestanden_buiten_het_image():
    regels = (ROOT / ".dockerignore").read_text().splitlines()
    for r in (".env", "secrets", "compose.yaml", "compose.build.yaml", "deploy"):
        assert r in regels, r


def test_image_tag_en_andere_compose_variabelen_hinderen_de_app_niet(tmp_path, monkeypatch):
    """IMAGE_TAG heeft geen WISSELWEER_-voorvoegsel; ook via .env of omgeving: genegeerd."""
    from wisselweer.settings import Settings

    env = tmp_path / ".env"
    env.write_text(
        "IMAGE_TAG=0.1.0\nPUBLISH_EVERY_HOURS=6\nCOMPOSE_PROFILES=publish\nWISSELWEER_PORT=9000\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("IMAGE_TAG", "ci")
    s = Settings(_env_file=env)
    assert s.port == 9000
    assert not hasattr(s, "image_tag")


def test_versie_in_pyproject_en_pakket_zijn_gelijk():
    """De release-workflow eist tag = v + versie; beide plekken moeten dus gelijk blijven."""
    from wisselweer import __version__

    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["version"] == __version__


# --- Workflows (tekst) ---------------------------------------------------------------------------


def test_release_workflow_tekst():
    tekst = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
    for needle in (
        'tags: ["v*"]',
        "IMAGE: ghcr.io/roeltje/wisselweer",
        "platforms: linux/amd64,linux/arm64",
        "provenance: mode=max",
        "sbom: true",
        "type=semver,pattern={{version}}",
        "type=semver,pattern={{major}}.{{minor}}",
        "type=raw,value=latest",
        "push-to-registry: true",
        "subject-digest: ${{ steps.build.outputs.digest }}",
        "gh release create",
        "release-assets/docker-install.sh",
        "release-assets/env.example",
        "GITHUB_REF_NAME",
    ):
        assert needle in tekst, needle
    # Actions op major-tags (Dependabot werkt ze bij), nooit op een branch of SHA zonder commentaar.
    for gebruikt in re.findall(r"uses: (\S+)", tekst):
        assert re.fullmatch(r"[\w./-]+@v\d+", gebruikt), gebruikt
    # Geen geheimen buiten GITHUB_TOKEN.
    assert set(re.findall(r"secrets\.(\w+)", tekst)) == {"GITHUB_TOKEN"}


def test_ci_workflow_heeft_een_losse_docker_job():
    tekst = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
    assert re.search(r"^  docker:\n", tekst, re.M)
    assert re.search(r"^  test:\n", tekst, re.M)
    docker = tekst.split("\n  docker:\n", 1)[1]
    for needle in (
        "load: true",
        "tags: ghcr.io/roeltje/wisselweer:ci",
        "type=gha",
        "deploy/docker-install.sh",
        "WISSELWEER_ASSETS_DIR",
        "IMAGE_TAG: ci",
        "/api/v1/health",
        "id -u",
        "create-admin --username ci --password-stdin",
        "sha256sum .env",
        "docker compose --profile publish config",
        "down -v",
    ):
        assert needle in docker, needle
    assert "needs:" not in docker  # parallel aan `test`


# --- Workflows (structuur, alleen met PyYAML) ----------------------------------------------------


def _laad(naam: str) -> dict:
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load((WORKFLOWS / naam).read_text(encoding="utf-8"))


def test_workflows_zijn_geldige_yaml_met_minimale_rechten():
    release = _laad("release.yml")
    triggers = release.get("on", release.get(True))
    assert triggers == {"push": {"tags": ["v*"]}}
    assert release["permissions"] == {"contents": "read"}
    image, rel = release["jobs"]["image"], release["jobs"]["release"]
    assert image["permissions"] == {
        "contents": "read",
        "packages": "write",
        "id-token": "write",
        "attestations": "write",
    }
    assert rel["permissions"] == {"contents": "write"}  # alleen de release-job mag schrijven
    assert rel["needs"] == "image"

    ci = _laad("ci.yml")
    assert ci["permissions"] == {"contents": "read"}
    assert set(ci["jobs"]) == {"test", "docker"}
    assert "needs" not in ci["jobs"]["docker"]


def test_compose_yaml_structuur():
    yaml = pytest.importorskip("yaml")
    data = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    web, pub = data["services"]["wisselweer"], data["services"]["publisher"]
    for service in (web, pub):
        assert service["read_only"] is True
        assert service["cap_drop"] == ["ALL"]
        assert service["security_opt"] == ["no-new-privileges:true"]
        assert service["tmpfs"] == ["/tmp"]  # noqa: S108
    assert web["ports"] == ["127.0.0.1:8000:8000"]
    assert "profiles" not in web and pub["profiles"] == ["publish"]
    assert web["volumes"] == ["wisselweer-data:/data"]
    assert pub["healthcheck"] == {"disable": True}
    assert [v["target"] for v in pub["volumes"] if isinstance(v, dict)] == ["/run/secrets"]
    assert "build" not in web and "secrets" not in web and "secrets" not in data
