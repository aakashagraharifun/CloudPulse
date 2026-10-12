"""Application configuration loaded from environment variables.

Values are read from the process environment first, then from `.env` files
(the backend directory and the repository root), so the same `.env` used by
Docker Compose also configures a locally running API.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_REPO_ROOT = _BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(_REPO_ROOT / ".env", _BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "CloudPulse API"
    environment: str = Field(default="development", description="development | test | production")
    log_level: str = "INFO"
    log_json: bool = False

    # PostgreSQL. The password has no default and must be provided via .env.
    # 127.0.0.1 (not "localhost"): on Windows "localhost" may resolve to IPv6 ::1
    # first, while Docker publishes the ports on IPv4 127.0.0.1 only.
    postgres_host: str = "127.0.0.1"
    postgres_port: int = 5432
    postgres_db: str = "cloudpulse"
    postgres_user: str = "cloudpulse"
    postgres_password: SecretStr

    # Redis / Celery
    redis_url: str = "redis://127.0.0.1:6379/0"

    # CORS: the browser calls the API directly from the Next.js dev server.
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    # Authentication
    session_ttl_hours: int = 12
    auth_max_failed_logins: int = 5
    auth_lockout_minutes: int = 15

    # Billing ingestion limits
    max_upload_bytes: int = 20 * 1024 * 1024
    max_upload_rows: int = 500_000
    max_reported_errors: int = 200

    # Outbound notifications
    notification_timeout_seconds: float = 5.0
    smtp_host: str = "127.0.0.1"
    smtp_port: int = 1025
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_use_tls: bool = False
    smtp_from: str = "cloudpulse@localhost"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_url(self) -> str:
        return self.database_url_for(self.postgres_db)

    def database_url_for(self, database: str) -> str:
        return URL.create(
            drivername="postgresql+psycopg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=database,
        ).render_as_string(hide_password=False)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
