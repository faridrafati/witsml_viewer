"""Environment-driven application settings.

Single source of truth for runtime config. Mirrors `.env.example` 1:1.
Nothing in the codebase should read `os.environ` directly — import `settings`.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── App ──
    app_env: str = "development"
    log_level: str = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # ── Database ──
    database_url: str = "sqlite+aiosqlite:///./witsml.db"

    # ── Redis (optional; in-process fallback when empty) ──
    redis_url: str | None = "redis://redis:6379/0"

    # ── WITSML server ──
    witsml_url: str = "http://drillflow:7070/Witsml/Store"
    witsml_username: str = "witsml"
    witsml_password: str = "witsml"
    witsml_verify_ssl: bool = True
    witsml_wsdl_path: str | None = None

    # ── Ingestion ──
    poll_interval_seconds: float = 5.0
    ingest_concurrency: int = 5
    ingest_stagger_ms: int = 250
    ring_buffer_hours: float = 6.0
    max_return_nodes: int = 1000
    simulated_well_count: int = 20

    # ── Security ──
    secret_key: str = "change-me-in-production-minimum-32-bytes-long"
    jwt_alg: str = "HS256"
    jwt_expire_minutes: int = 720
    credential_encryption_key: str | None = None

    # ── Bootstrap super-admin ──
    superadmin_username: str = "admin"
    superadmin_password: str = "admin"

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def redis_enabled(self) -> bool:
        return bool(self.redis_url)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
