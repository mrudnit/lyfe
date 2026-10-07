"""Application configuration, loaded from environment variables.

Works both with a self-managed Postgres (POSTGRES_* variables) and with hosting
platforms that inject a single DATABASE_URL, such as Railway, Render or Heroku.
If DATABASE_URL is present it wins.
"""
import re
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Telegram
    bot_token: str
    bot_username: str = "LYFE_REQUEST_BOT"

    # Postgres. Either a full URL from the platform...
    database_url_raw: str = Field("", validation_alias="DATABASE_URL")

    # ...or the individual parts, for docker-compose and local runs.
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
    # Only the first N likes per event are paid. Without a cap a person could
    # like all ten tracks in TOP from their sofa and out-earn someone who
    # actually turned up.
    max_paid_votes_per_event: int = 3
    points_attendance: int = 10
    cost_priority_track: int = 40
    # BOOST: spend points to lift a track in TOP REQUESTS, one point = one place
    # of score. Capped per night so a full wallet cannot buy the whole chart.
    cost_boost: int = 5
    max_boosts_per_event: int = 3

    # Mini App. The public https address of the web service, e.g.
    # https://lyfe-web-production.up.railway.app — the bot opens <url>/app.
    # Empty means the bot keeps working with chat buttons only.
    webapp_url: str = ""

    # Web admin / DJ screen
    admin_secret_key: str = "change-me"
    web_host: str = "0.0.0.0"
    web_port: int = 8000

    sentry_dsn: str = ""

    @property
    def database_url(self) -> str:
        if self.database_url_raw:
            return _to_asyncpg_url(self.database_url_raw)
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


def _to_asyncpg_url(url: str) -> str:
    """Normalise a platform-provided connection string for asyncpg.

    Platforms hand out URLs in the psycopg dialect and often append query
    parameters that asyncpg refuses to parse, so both are fixed here rather
    than asking anyone to edit the value by hand.
    """
    for prefix in ("postgresql+psycopg2://", "postgresql+psycopg://", "postgresql://", "postgres://"):
        if url.startswith(prefix):
            url = "postgresql+asyncpg://" + url[len(prefix):]
            break

    # asyncpg configures TLS through connect_args, not the query string.
    url = re.sub(r"[?&]sslmode=[^&]*", "", url)
    url = re.sub(r"[?&]channel_binding=[^&]*", "", url)
    return url.rstrip("?&")


@lru_cache
def get_settings() -> Settings:
    return Settings()
