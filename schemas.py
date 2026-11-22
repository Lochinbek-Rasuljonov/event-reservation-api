from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from models import SeatStatus


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)

    @field_validator("password")
    @classmethod
    def fits_bcrypt(cls, value: str) -> str:
        # bcrypt only looks at the first 72 bytes, so longer passwords are refused
        if len(value.encode()) > 72:
            raise ValueError("Password must be at most 72 bytes")
        return value


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    is_admin: bool


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class SeatResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    seat_number: str
    status: SeatStatus


class EventCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
    date: datetime
    price: float = Field(ge=0)
    seat_count: int = Field(ge=1, le=5000)

    @field_validator("date")
    @classmethod
    def to_naive_utc(cls, value: datetime) -> datetime:
        # Dates are stored as UTC without a time zone
        return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


class EventSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: Optional[str]
    date: datetime
    price: float
    available_seats: int = 0


class EventResponse(EventSummary):
    seats: list[SeatResponse] = []


class ReservationRequest(BaseModel):
    seat_id: int


class ReservationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    seat_id: int
    created_at: datetime
    expires_at: datetime
    status: SeatStatus
