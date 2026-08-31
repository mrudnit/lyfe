"""Cities and venues. Multi-city support from day one — cheap now, expensive later."""
from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lyfe.models.base import Base, PKMixin, TimestampMixin


class City(PKMixin, TimestampMixin, Base):
    __tablename__ = "cities"

    name: Mapped[str] = mapped_column(String(80), nullable=False)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False, default="SK")
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Europe/Bratislava")

    venues: Mapped[list["Venue"]] = relationship(back_populates="city")


class Venue(PKMixin, TimestampMixin, Base):
    __tablename__ = "venues"

    city_id: Mapped[int] = mapped_column(ForeignKey("cities.id", ondelete="RESTRICT"), index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    address: Mapped[str | None] = mapped_column(Text)
    capacity: Mapped[int | None] = mapped_column(Integer)
    instagram: Mapped[str | None] = mapped_column(String(120))
    website: Mapped[str | None] = mapped_column(String(255))

    city: Mapped["City"] = relationship(back_populates="venues")
