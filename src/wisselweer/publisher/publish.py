"""Publiceren van `advice.json`: atomisch lokaal schrijven en optioneel SFTP-upload."""

from __future__ import annotations

import logging
import os
import re
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import ValidationError

from wisselweer.publisher.national import NationalAdviceService
from wisselweer.publisher.public_schema import PublicAdvice

if TYPE_CHECKING:
    from wisselweer.settings import Settings
    from wisselweer.weather.service import ForecastService

log = logging.getLogger("wisselweer.publisher")

FILENAME = "advice.json"
SFTP_TIMEOUT_S = 60

_HOST_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")
_USER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,31}$")
_REMOTE_DIR_RE = re.compile(r"^[A-Za-z0-9._/~-]{1,255}$")
_BAD_LOCAL_CHARS = re.compile(r'["\\\x00-\x1f\x7f]')


class PublishError(Exception):
    """Publicatie mislukt; de boodschap bevat geen secrets of sleutelpaden."""


def write_local(advice: PublicAdvice, directory: Path) -> Path:
    """Schrijft `advice.json` atomisch: tmp-bestand, terugleesvalidatie, `os.replace`."""
    directory = Path(directory)
    if not directory.is_dir():
        raise PublishError("publicatiemap bestaat niet")
    target = directory / FILENAME
    tmp = directory / f"{FILENAME}.tmp"
    try:
        tmp.write_text(advice.model_dump_json(indent=2) + "\n", encoding="utf-8")
        os.chmod(tmp, 0o644)
        PublicAdvice.model_validate_json(tmp.read_text(encoding="utf-8"))
        os.replace(tmp, target)
    except (ValidationError, ValueError, OSError) as exc:
        tmp.unlink(missing_ok=True)
        raise PublishError(f"advice.json niet geschreven ({type(exc).__name__})") from exc
    return target


def _check_sftp_args(host: str, user: str, remote_dir: str, port: int, local_file: Path) -> None:
    if not _HOST_RE.fullmatch(host):
        raise PublishError("ongeldige SFTP-host")
    if not _USER_RE.fullmatch(user):
        raise PublishError("ongeldige SFTP-gebruiker")
    if not _REMOTE_DIR_RE.fullmatch(remote_dir) or ".." in remote_dir.split("/"):
        raise PublishError("ongeldig SFTP-doelpad")
    if not 1 <= port <= 65535:
        raise PublishError("ongeldige SFTP-poort")
    if _BAD_LOCAL_CHARS.search(str(local_file)):
        raise PublishError("lokaal pad bevat niet-ondersteunde tekens")


def build_sftp_command(
    key_path: Path, host: str, user: str, port: int = 22, known_hosts: Path | None = None
) -> list[str]:
    cmd = [
        "sftp",
        "-b",
        "-",
        "-i",
        str(key_path),
        "-P",
        str(port),
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        "IdentitiesOnly=yes",
    ]
    if known_hosts is not None:
        cmd += ["-o", f"UserKnownHostsFile={known_hosts}"]
    cmd.append(f"{user}@{host}")
    return cmd


def publish_sftp(
    local_file: Path,
    host: str,
    user: str,
    key_path: Path,
    remote_dir: str,
    port: int = 22,
    known_hosts: Path | None = None,
) -> None:
    """Uploadt naar `<remote_dir>/advice.json.tmp` en hernoemt naar `advice.json`.

    Het `rename`-commando van OpenSSH `sftp` gebruikt `posix-rename@openssh.com` wanneer de
    server dat ondersteunt (OpenSSH-servers doen dat), waardoor een bestaand `advice.json`
    atomisch wordt vervangen. Zonder die extensie faalt de rename als het doel bestaat.
    Argumenten gaan als lijst naar `subprocess.run` (geen shell); host, gebruiker en paden
    worden vooraf gevalideerd.
    """
    local_file = Path(local_file)
    remote_dir = remote_dir.rstrip("/") or "/"
    _check_sftp_args(host, user, remote_dir, port, local_file)
    base = "" if remote_dir == "/" else remote_dir
    remote_tmp, remote_final = f"{base}/{FILENAME}.tmp", f"{base}/{FILENAME}"
    batch = f'put "{local_file}" "{remote_tmp}"\nrename "{remote_tmp}" "{remote_final}"\n'
    cmd = build_sftp_command(Path(key_path), host, user, port, known_hosts)
    try:
        proc = subprocess.run(  # noqa: S603 - vaste binary, lijst-argumenten, gevalideerde invoer
            cmd,
            input=batch,
            capture_output=True,
            text=True,
            timeout=SFTP_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise PublishError("SFTP-upload: time-out") from exc
    except OSError as exc:
        raise PublishError("SFTP-upload: sftp-commando niet beschikbaar") from exc
    if proc.returncode != 0:
        log.debug("sftp stderr: %s", (proc.stderr or "")[-500:])
        raise PublishError(f"SFTP-upload mislukt (exitcode {proc.returncode})")
    log.info("sftp_upload_ok host=%s", host)


def build_default_forecast_service(settings: Settings) -> ForecastService:
    """Forecastservice met SQLite-cache in `data_dir` (zoals de webapp)."""
    from wisselweer.api.deps import apply_default_provider_setting
    from wisselweer.storage.cache_backend import SqliteCacheBackend
    from wisselweer.storage.db import make_engine, make_session_factory, migrate
    from wisselweer.weather.registry import build_forecast_service

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    url = f"sqlite:///{(settings.data_dir / 'wisselweer.db').resolve()}"
    migrate(url)
    factory = make_session_factory(make_engine(url))
    service = build_forecast_service(settings.providers_config(), SqliteCacheBackend(factory))
    apply_default_provider_setting(factory, service)
    return service


def run_publish(
    settings: Settings, forecast_service: ForecastService | None = None
) -> PublicAdvice:
    service = forecast_service or build_default_forecast_service(settings)
    advice = NationalAdviceService(service, settings.national_config()).compute()
    if settings.publish_countries:
        from wisselweer.publisher.countries import build_public_countries

        countries, disclaimer = build_public_countries(service, advice.generated_at)
        advice = advice.model_copy(
            update={"countries": countries, "countries_disclaimer": disclaimer}
        )
    directory = settings.publish_dir
    directory.mkdir(parents=True, exist_ok=True)
    target = write_local(advice, directory)
    log.info("advice_written status=%s", advice.status)
    if settings.publish_sftp_host:
        if not settings.publish_sftp_user or settings.publish_sftp_key is None:
            raise PublishError("SFTP onvolledig ingesteld (gebruiker of sleutel ontbreekt)")
        publish_sftp(
            target,
            settings.publish_sftp_host,
            settings.publish_sftp_user,
            settings.publish_sftp_key,
            settings.publish_sftp_path,
            port=settings.publish_sftp_port,
            known_hosts=settings.publish_sftp_known_hosts,
        )
    return advice
