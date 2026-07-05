from pydantic import BaseModel, EmailStr
from datetime import datetime
from typing import List, Optional
from models import SeatStatus

class UserCreate(BaseModel):
    email: EmailStr
    password: str

class UserResponse(BaseModel):
    id: int
    email: EmailStr

    class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str

class SeatResponse(BaseModel):
    id: int
    seat_number: str
    status: SeatStatus

    class Config:
        from_attributes = True

class EventCreate(BaseModel):
    title: str
    description: Optional[str] = None
    date: datetime
    price: float
    seat_count: int

class EventResponse(BaseModel):
    id: int
    title: str
    description: Optional[str]
    date: datetime
    price: float
    seats: List[SeatResponse] = []

    class Config:
        from_attributes = True

class ReservationRequest(BaseModel):
    seat_id: int

class ReservationResponse(BaseModel):
    id: int
    user_id: int
    seat_id: int
    created_at: datetime
    expires_at: datetime
    is_active: SeatStatus

    class Config:
        from_attributes = True
