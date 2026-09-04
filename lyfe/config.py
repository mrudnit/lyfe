"""Application configuration, loaded from environment variables."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Telegram
    bot_token: str
    bot_username: str = "LYFE_REQUEST_BOT"

    # Postgres
    postgres_user: str = "lyfe"
    postgres_password: str = "lyfe"
    postgres_db: str = "lyfe"
    postgres_host: str = "postgres"
    postgres_port: int = 5432

    # Redis
    redis_url: str = "redis://redis:6379/0"

    # App
    default_language: str = "ru"
    env: str = "dev"
    log_level: str = "INFO"

    # Limits
    max_requests_per_user_per_event: int = 3

    # Points
    points_music_request: int = 1
    # Zero on purpose: liking is free and pleasant, and paying for it let a
    # person on their sofa out-earn someone who actually turned up.
    points_vote: int = 0
    points_attendance: int = 10
    cost_priority_track: int = 40

    # Web admin / DJ screen
    admin_secret_key: str = "change-me"
    web_host: str = "0.0.0.0"
    web_port: int = 8000

    sentry_dsn: str = ""

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
