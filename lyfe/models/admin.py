"""Admin accounts and the audit log."""
from sqlalchemy import BigInteger, Boolean, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from lyfe.models.base import Base, PKMixin, TimestampMixin


class AdminRole:
    SUPER_ADMIN = "SUPER_ADMIN"
    ADMIN = "ADMIN"
    DJ = "DJ"
    MODERATOR = "MODERATOR"
    PHOTOGRAPHER = "PHOTOGRAPHER"

    ALL = (SUPER_ADMIN, ADMIN, DJ, MODERATOR, PHOTOGRAPHER)


class AdminUser(PKMixin, TimestampMixin, Base):
    __tablename__ = "admin_users"

    # Optional link to a Telegram user, so an admin can also be a normal guest.
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    login: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(80))
    role: Mapped[str] = mapped_column(String(16), nullable=False, default=AdminRole.DJ)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class AdminAction(PKMixin, TimestampMixin, Base):
    """Every meaningful admin action is written here. Never deleted."""

    __tablename__ = "admin_actions"

    admin_id: Mapped[int | None] = mapped_column(
        ForeignKey("admin_users.id", ondelete="SET NULL"), index=True
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_type: Mapped[str | None] = mapped_column(String(48))
    target_id: Mapped[int | None] = mapped_column(BigInteger)
    old_value: Mapped[dict | None] = mapped_column(JSONB)
    new_value: Mapped[dict | None] = mapped_column(JSONB)
    note: Mapped[str | None] = mapped_column(Text)
    ip: Mapped[str | None] = mapped_column(String(64))
