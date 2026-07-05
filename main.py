from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from jose import JWTError, jwt
from passlib.context import CryptContext
from datetime import datetime, timedelta
from typing import List

import os
from database import get_db, Base, engine
from models import User, Event, Seat, Reservation, SeatStatus
from schemas import UserCreate, UserResponse, Token, EventCreate, EventResponse, ReservationRequest, ReservationResponse

# Security & JWT Configuration
SECRET_KEY = os.getenv("SECRET_KEY", "supersecretkeyforreservationapp")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

app = FastAPI(title="Real-Time Event Reservation API")

# Startup DB Initialization
@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

# Auth Helpers
def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user(token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    
    query = select(User).where(User.email == email)
    result = await db.execute(query)
    user = result.scalar_one_or_none()
    if user is None:
        raise credentials_exception
    return user

# --- AUTH ENDPOINTS ---
@app.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(user_in: UserCreate, db: AsyncSession = Depends(get_db)):
    query = select(User).where(User.email == user_in.email)
    result = await db.execute(query)
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")
    
    hashed_pwd = get_password_hash(user_in.password)
    user = User(email=user_in.email, hashed_password=hashed_pwd)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user

@app.post("/token", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends(), db: AsyncSession = Depends(get_db)):
    query = select(User).where(User.email == form_data.username)
    result = await db.execute(query)
    user = result.scalar_one_or_none()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Incorrect email or password")
    
    access_token = create_access_token(data={"sub": user.email}, expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    return {"access_token": access_token, "token_type": "bearer"}

# --- EVENT ENDPOINTS ---
@app.post("/events", response_model=EventResponse, status_code=status.HTTP_201_CREATED)
async def create_event(event_in: EventCreate, db: AsyncSession = Depends(get_db)):
    event = Event(title=event_in.title, description=event_in.description, date=event_in.date, price=event_in.price)
    db.add(event)
    await db.flush() # Flush to get event.id
    
    # Pre-populate seats
    seats = []
    for i in range(1, event_in.seat_count + 1):
        seat_num = f"Seat-{i:03d}"
        seat = Seat(event_id=event.id, seat_number=seat_num, status=SeatStatus.AVAILABLE)
        seats.append(seat)
    db.add_all(seats)
    await db.commit()
    await db.refresh(event)
    return event

@app.get("/events", response_model=List[EventResponse])
async def list_events(db: AsyncSession = Depends(get_db)):
    query = select(Event)
    result = await db.execute(query)
    return result.scalars().all()

@app.get("/events/{event_id}", response_model=EventResponse)
async def get_event(event_id: int, db: AsyncSession = Depends(get_db)):
    query = select(Event).where(Event.id == event_id)
    result = await db.execute(query)
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return event

# --- RESERVATION ENDPOINTS ---
@app.post("/reservations", response_model=ReservationResponse, status_code=status.HTTP_201_CREATED)
async def reserve_seat(req: ReservationRequest, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    # Concurrency control: Lock the specific seat row during evaluation
    # This prevents race conditions where two threads try to reserve the same seat simultaneously.
    query = select(Seat).where(Seat.id == req.seat_id).with_for_update()
    result = await db.execute(query)
    seat = result.scalar_one_or_none()
    
    if not seat:
        raise HTTPException(status_code=404, detail="Seat not found")
    
    if seat.status != SeatStatus.AVAILABLE:
        raise HTTPException(status_code=409, detail="Seat is already reserved or booked")
    
    # Mark seat as reserved
    seat.status = SeatStatus.RESERVED
    
    # Create temporary hold reservation
    reservation = Reservation(
        user_id=current_user.id,
        seat_id=seat.id,
        is_active=SeatStatus.RESERVED
    )
    db.add(reservation)
    await db.commit()
    await db.refresh(reservation)
    return reservation

@app.post("/reservations/{reservation_id}/confirm", response_model=ReservationResponse)
async def confirm_booking(reservation_id: int, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    query = select(Reservation).where(
        Reservation.id == reservation_id,
        Reservation.user_id == current_user.id
    ).with_for_update()
    result = await db.execute(query)
    reservation = result.scalar_one_or_none()
    
    if not reservation:
        raise HTTPException(status_code=404, detail="Active reservation hold not found")
    
    if reservation.is_active != SeatStatus.RESERVED:
        raise HTTPException(status_code=400, detail="Reservation hold is not in reserved state")
    
    # Check expiry
    if reservation.expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Reservation hold has expired. Please reserve again.")
    
    # Finalize booking
    reservation.is_active = SeatStatus.BOOKED
    
    await db.execute(
        update(Seat)
        .where(Seat.id == reservation.seat_id)
        .values(status=SeatStatus.BOOKED)
    )
    await db.commit()
    await db.refresh(reservation)
    return reservation
