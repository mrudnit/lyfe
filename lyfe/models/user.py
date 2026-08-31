"""Users. Minimal personal data by design — GDPR data minimisation."""
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from lyfe.models.base import Base, PKMixin, TimestampMixin


class User(PKMixin, TimestampMixin, Base):
    __tablename__ = "users"

    # Telegram identity — this is our only authentication source.
    tg_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    tg_username: Mapped[str | None] = mapped_column(String(64))
    first_name: Mapped[str | None] = mapped_column(String(120))

    # Public brand identifier. NOT a secret, NOT an auth token. Format: "0842".
    lyfe_id: Mapped[str] = mapped_column(String(12), unique=True, nullable=False, index=True)

    # Optional name the user chose for themselves inside LYFE.
    display_name: Mapped[str | None] = mapped_column(String(64))

    language: Mapped[str] = mapped_column(String(5), nullable=False, default="sk")

    is_blocked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_bot_blocked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Soft delete for GDPR erasure requests.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def name(self) -> str:
        return self.display_name or self.first_name or f"LYFE #{self.lyfe_id}"
