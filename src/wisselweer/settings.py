"""Applicatie-instellingen uit omgevingsvariabelen (`WISSELWEER_*`) en optioneel `.env`."""

from __future__ import annotations

import ipaddress
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from wisselweer.publisher.national import ReferenceLocation

MIN_SECRET_KEY_LENGTH = 32
DEFAULT_GEOCODER_URL = "https://nominatim.openstreetmap.org"
# Waarden die geocoderen uitzetten. Een lege omgevingsvariabele telt als "niet gezet" (zie
# `env_ignore_empty`), dus uitzetten via de omgeving kan met "off".
_GEOCODER_OFF = {"", "off", "none", "false", "0", "uit"}

if TYPE_CHECKING:
    from wisselweer.publisher.national import NationalConfig
    from wisselweer.weather.registry import ProvidersConfig


def is_loopback_host(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _require_https(value: str, name: str) -> str:
    """Alleen https-URL's; http alleen voor localhost of een loopback-adres."""
    parts = urlparse(value.strip())
    host = parts.hostname or ""
    if parts.scheme == "https" and host:
        return value.strip()
    if parts.scheme == "http" and is_loopback_host(host):
        return value.strip()
    raise ValueError(
        f"{name} moet een https://-URL zijn "
        "(http:// is alleen toegestaan voor localhost of een loopback-adres)"
    )


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="WISSELWEER_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=True,
        # Foutmeldingen mogen de ingevoerde waarde (secret key, API-keys) niet herhalen.
        hide_input_in_errors=True,
    )

    host: str = "127.0.0.1"
    port: int = 8000
    data_dir: Path = Path("./data")
    # Contactgegeven voor de MET Norway User-Agent; bewust geen default.
    contact: str | None = None
    default_provider: str = "metno"
    commercial: bool = False
    openmeteo_base_url: str = "https://api.open-meteo.com"
    # Nominatim-compatibele geocoder (adres/plaats -> coördinaten). Leeg of "off" = uit. Vereist `contact`.
    geocoder_url: str = DEFAULT_GEOCODER_URL
    openmeteo_api_key: SecretStr | None = None
    knmi_api_key: SecretStr | None = None
    wu_api_key: SecretStr | None = None
    knmi_station_id: str | None = None
    wu_station_id: str | None = None
    max_stale_hours: int = 24
    default_latitude: float | None = None
    default_longitude: float | None = None
    timezone: str = "Europe/Amsterdam"
    secret_key: SecretStr | None = None
    cookie_secure: bool = False
    log_level: str = "INFO"
    # Vanaf deze leeftijd (jaren, uit de DOT-code) tonen we een waarschuwing bij een band.
    tire_age_warn_years: float = Field(default=8, gt=0, le=30)
    # /docs (Swagger UI, laadt van een CDN) en /openapi.json; uit = beide routes bestaan niet.
    enable_docs: bool = True

    # --- Publicatie van het landelijke advies (`wisselweer publish`) ---
    publish_dir: Path | None = None  # standaard <data_dir>/public
    publish_sftp_host: str | None = None
    publish_sftp_user: str | None = None
    publish_sftp_key: Path | None = None
    publish_sftp_path: str = "/"
    publish_sftp_port: int = 22
    publish_sftp_known_hosts: Path | None = None
    public_stale_hours: float = 18
    # Interne publicatieplanner: 0 = uit, anders elke N uur (eerste run na 1 minuut).
    publish_interval_hours: int = 0
    # Landenregels (winterbanden) meepubliceren in advice.json; kost extra verwachtingen per run.
    publish_countries: bool = False
    # Optionele JSON-lijst [{"name": ..., "latitude": ..., "longitude": ...}] i.p.v. de standaard.
    national_locations: list[ReferenceLocation] | None = None

    @field_validator("secret_key")
    @classmethod
    def _secret_key_length(cls, value: SecretStr | None) -> SecretStr | None:
        """Leeg = automatisch genereren (None); anders minimaal 32 tekens. De waarde zelf staat nooit in de fout."""
        if value is None or value.get_secret_value() == "":
            return None
        if len(value.get_secret_value()) < MIN_SECRET_KEY_LENGTH:
            raise ValueError(
                f"WISSELWEER_SECRET_KEY moet minimaal {MIN_SECRET_KEY_LENGTH} tekens bevatten "
                "(of leeg zijn: dan wordt een sleutel gegenereerd)"
            )
        return value

    @field_validator("openmeteo_base_url")
    @classmethod
    def _https_base_url(cls, value: str) -> str:
        """De Open-Meteo-URL kan een API-key in de query-string dragen: alleen https (of loopback)."""
        return _require_https(value, "WISSELWEER_OPENMETEO_BASE_URL")

    @field_validator("geocoder_url")
    @classmethod
    def _geocoder_url(cls, value: str) -> str:
        """Leeg/"off" = uit; anders https (of loopback) zodat zoektekst niet onversleuteld meegaat."""
        value = value.strip()
        if value.lower() in _GEOCODER_OFF:
            return ""
        return _require_https(value, "WISSELWEER_GEOCODER_URL").rstrip("/")

    @model_validator(mode="after")
    def _default_publish_dir(self) -> Settings:
        if self.publish_dir is None:
            self.publish_dir = self.data_dir / "public"
        return self

    @property
    def photos_dir(self) -> Path:
        """Voertuigfoto's; privé en nooit onderdeel van de publicatie."""
        return self.data_dir / "photos"

    @property
    def geocoding_enabled(self) -> bool:
        """Geocoderen staat aan met een URL én een contactgegeven (verplicht voor de User-Agent)."""
        return bool(self.geocoder_url) and bool((self.contact or "").strip())

    def national_config(self) -> NationalConfig:
        from wisselweer.publisher.national import NationalConfig

        cfg = NationalConfig(stale_hours=self.public_stale_hours)
        if self.national_locations:
            cfg = cfg.model_copy(update={"locations": self.national_locations})
        return cfg

    def providers_config(self) -> ProvidersConfig:
        from wisselweer.weather.registry import ProvidersConfig

        return ProvidersConfig(
            contact=self.contact,
            commercial=self.commercial,
            openmeteo_base_url=self.openmeteo_base_url,
            openmeteo_api_key=self.openmeteo_api_key,
            knmi_api_key=self.knmi_api_key,
            knmi_station_id=self.knmi_station_id,
            wu_api_key=self.wu_api_key,
            wu_station_id=self.wu_station_id,
            default_provider=self.default_provider,
            max_stale_hours=self.max_stale_hours,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
