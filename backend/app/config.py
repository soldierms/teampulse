from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://teampulse:teampulse@localhost:5432/teampulse"

    secret_key: str = ""
    credentials_encryption_key: str = ""
    session_ttl_hours: int = 720
    cors_origins: str = "http://localhost:5173"
    log_level: str = "INFO"

    pagerduty_api_key: str = ""
    pagerduty_client_id: str = ""
    pagerduty_client_secret: str = ""

    github_client_id: str = ""
    github_client_secret: str = ""
    github_oauth_redirect_url: str = "http://localhost:8000/api/integrations/github/callback"

    sync_interval_minutes: int = 15
    worker_poll_seconds: int = 5

    notifier: str = "console"
    digest_from_email: str = "teampulse@example.com"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    resend_api_key: str = ""
    slack_webhook_url: str = ""

    metrics_config_path: Path = BACKEND_ROOT / "metrics.yaml"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
