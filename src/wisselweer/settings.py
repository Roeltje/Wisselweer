"""Applicatie-instellingen uit omgevingsvariabelen (`WISSELWEER_*`) en optioneel `.env`."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from wisselweer.publisher.national import ReferenceLocation

if TYPE_CHECKING:
    from wisselweer.publisher.national import NationalConfig
    from wisselweer.weather.registry import ProvidersConfig


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="WISSELWEER_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=True,
    )

    host: str = "127.0.0.1"
    port: int = 8000
    data_dir: Path = Path("./data")
    # Contactgegeven voor de MET Norway User-Agent; bewust geen default.
    contact: str | None = None
    default_provider: str = "metno"
    commercial: bool = False
    openmeteo_base_url: str = "https://api.open-meteo.com"
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
    # Optionele JSON-lijst [{"name": ..., "latitude": ..., "longitude": ...}] i.p.v. de standaard.
    national_locations: list[ReferenceLocation] | None = None

    @model_validator(mode="after")
    def _default_publish_dir(self) -> Settings:
        if self.publish_dir is None:
            self.publish_dir = self.data_dir / "public"
        return self

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
