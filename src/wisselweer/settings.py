"""Applicatie-instellingen uit omgevingsvariabelen (`WISSELWEER_*`) en optioneel `.env`."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
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
