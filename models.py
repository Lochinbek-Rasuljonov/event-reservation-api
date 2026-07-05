from datetime import datetime, timedelta
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Enum, UniqueConstraint
from sqlalchemy.orm import relationship
import enum
from database import Base

class SeatStatus(str, enum.Enum):
    AVAILABLE = "available"
    RESERVED = "reserved"  # Temporary hold (e.g. 10 mins during checkout)
    BOOKED = "booked"      # Permanently purchased

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    reservations = relationship("Reservation", back_populates="user")

class Event(Base):
    __tablename__ = "events"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    description = Column(String)
    date = Column(DateTime, nullable=False)
    price = Column(Float, nullable=False)
    seats = relationship("Seat", back_populates="event", cascade="all, delete-orphan")

class Seat(Base):
    __tablename__ = "seats"
    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(Integer, ForeignKey("events.id", ondelete="CASCADE"), nullable=False)
    seat_number = Column(String, nullable=False)
    status = Column(Enum(SeatStatus), default=SeatStatus.AVAILABLE, nullable=False)
    
    event = relationship("Event", back_populates="seats")
    reservation = relationship("Reservation", back_populates="seat", uselist=False)

    __table_args__ = (
        UniqueConstraint("event_id", "seat_number", name="uq_event_seat"),
    )

class Reservation(Base):
    __tablename__ = "reservations"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    seat_id = Column(Integer, ForeignKey("seats.id", ondelete="CASCADE"), unique=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, default=lambda: datetime.utcnow() + timedelta(minutes=10))
    is_active = Column(Enum(SeatStatus), default=SeatStatus.RESERVED, nullable=False)

    user = relationship("User", back_populates="reservations")
    seat = relationship("Seat", back_populates="reservation")
