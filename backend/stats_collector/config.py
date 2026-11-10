"""Runtime configuration, read from environment variables and /etc/stats-collector/config.env."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

CONFIG_FILE = os.environ.get("SC_CONFIG_FILE", "/etc/stats-collector/config.env")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SC_", env_file=CONFIG_FILE, env_file_encoding="utf-8", extra="ignore")

    env: str = "development"  # development | production
    database_url: str = "sqlite:///./stats-collector-dev.db"
    secret_key: str = "dev-insecure-secret-change-me"
    data_dir: Path = Path("./var")
    install_dir: Path = Path("/opt/stats-collector")
    public_url: str = "http://localhost:8080"
    host: str = "127.0.0.1"
    port: int = 8080
    livewall_port: int = 8081
    trusted_proxies: str = "127.0.0.1"
    default_channel: str = "test"  # test | production
    github_repo: str = "rhisijmuiden/stats-collector"
    github_token: str | None = None
    session_hours: int = 12
    pgbackrest_stanza: str = "stats-collector"
    static_dir: Path | None = Field(default=None)

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @property
    def cookie_secure(self) -> bool:
        return self.public_url.startswith("https://")

    @property
    def ops_dir(self) -> Path:
        return self.data_dir / "ops"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def backup_dir(self) -> Path:
        return self.data_dir / "backup"


@lru_cache
def get_settings() -> Settings:
    return Settings()
