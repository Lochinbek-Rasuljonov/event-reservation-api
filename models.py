import enum
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base

HOLD_MINUTES = 10


def utcnow() -> datetime:
    """Naive UTC time, to match the TIMESTAMP WITHOUT TIME ZONE columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def hold_expiry() -> datetime:
    return utcnow() + timedelta(minutes=HOLD_MINUTES)


class SeatStatus(str, enum.Enum):
    AVAILABLE = "available"
    RESERVED = "reserved"  # held for HOLD_MINUTES while the user checks out
    BOOKED = "booked"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(128))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)

    reservations: Mapped[list["Reservation"]] = relationship(back_populates="user")


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[Optional[str]] = mapped_column(String(2000))
    date: Mapped[datetime] = mapped_column(DateTime)
    price: Mapped[float] = mapped_column(Float)

    seats: Mapped[list["Seat"]] = relationship(
        back_populates="event", cascade="all, delete-orphan", order_by="Seat.id"
    )


class Seat(Base):
    __tablename__ = "seats"
    __table_args__ = (UniqueConstraint("event_id", "seat_number", name="uq_event_seat"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    seat_number: Mapped[str] = mapped_column(String(20))
    status: Mapped[SeatStatus] = mapped_column(
        Enum(SeatStatus, name="seat_status"), default=SeatStatus.AVAILABLE
    )

    event: Mapped[Event] = relationship(back_populates="seats")
    reservation: Mapped[Optional["Reservation"]] = relationship(back_populates="seat")


class Reservation(Base):
    __tablename__ = "reservations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # One reservation per seat: a seat is either held, booked, or free with no row here
    seat_id: Mapped[int] = mapped_column(ForeignKey("seats.id", ondelete="CASCADE"), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, default=hold_expiry)
    status: Mapped[SeatStatus] = mapped_column(
        Enum(SeatStatus, name="seat_status"), default=SeatStatus.RESERVED
    )

    user: Mapped[User] = relationship(back_populates="reservations")
    seat: Mapped[Seat] = relationship(back_populates="reservation")
