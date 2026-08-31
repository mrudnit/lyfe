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
    points_vote: int = 1
    points_attendance: int = 10

    sentry_dsn: str = ""

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def sync_database_url(self) -> str:
        """Alembic runs migrations synchronously."""
        return (
            f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
