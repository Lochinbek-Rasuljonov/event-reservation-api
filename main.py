import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from redis.asyncio import Redis
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database import Base, engine, get_db
from models import Event, Reservation, Seat, SeatStatus, User, utcnow
from ratelimit import limit_reservations
from schemas import (
    EventCreate,
    EventResponse,
    EventSummary,
    ReservationRequest,
    ReservationResponse,
    Token,
    UserCreate,
    UserResponse,
)
from security import create_access_token, hash_password, read_access_token, verify_password

ADMIN_EMAILS = {e.strip().lower() for e in os.getenv("ADMIN_EMAILS", "").split(",") if e.strip()}


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        # Several API workers start at once; the lock lets one create the tables at a time
        await conn.execute(text("SELECT pg_advisory_xact_lock(727274)"))
        await conn.run_sync(Base.metadata.create_all)
    app.state.redis = Redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"))
    yield
    await app.state.redis.aclose()
    await engine.dispose()


app = FastAPI(title="Real-Time Event Reservation API", lifespan=lifespan)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


async def get_current_user(token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)) -> User:
    email = read_access_token(token)
    user = await db.scalar(select(User).where(User.email == email)) if email else None
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def get_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only admins can do this")
    return user


@app.get("/health")
async def health():
    return {"status": "ok"}


# --- Auth ---
@app.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(user_in: UserCreate, db: AsyncSession = Depends(get_db)):
    email = user_in.email.lower()
    user = User(email=email, hashed_password=hash_password(user_in.password), is_admin=email in ADMIN_EMAILS)
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        raise HTTPException(status_code=400, detail="Email already registered")
    return user


@app.post("/token", response_model=Token)
async def login(form: OAuth2PasswordRequestForm = Depends(), db: AsyncSession = Depends(get_db)):
    user = await db.scalar(select(User).where(User.email == form.username.lower()))
    if not user or not verify_password(form.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Incorrect email or password")
    return Token(access_token=create_access_token(user.email))


# --- Events ---
def available_count():
    return (
        select(func.count(Seat.id))
        .where(Seat.event_id == Event.id, Seat.status == SeatStatus.AVAILABLE)
        .scalar_subquery()
    )


async def load_event(db: AsyncSession, event_id: int) -> EventResponse:
    event = await db.scalar(select(Event).options(selectinload(Event.seats)).where(Event.id == event_id))
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    response = EventResponse.model_validate(event)
    response.available_seats = sum(s.status == SeatStatus.AVAILABLE for s in event.seats)
    return response


@app.post("/events", response_model=EventResponse, status_code=status.HTTP_201_CREATED)
async def create_event(event_in: EventCreate, db: AsyncSession = Depends(get_db), _: User = Depends(get_admin)):
    event = Event(**event_in.model_dump(exclude={"seat_count"}))
    event.seats = [Seat(seat_number=f"Seat-{i:04d}") for i in range(1, event_in.seat_count + 1)]
    db.add(event)
    await db.commit()
    return await load_event(db, event.id)


@app.get("/events", response_model=list[EventSummary])
async def list_events(db: AsyncSession = Depends(get_db)):
    rows = await db.execute(select(Event, available_count()).order_by(Event.date))
    return [EventSummary.model_validate(e).model_copy(update={"available_seats": n}) for e, n in rows]


@app.get("/events/{event_id}", response_model=EventResponse)
async def get_event(event_id: int, db: AsyncSession = Depends(get_db)):
    return await load_event(db, event_id)


# --- Reservations ---
@app.post(
    "/reservations",
    response_model=ReservationResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(limit_reservations)],
)
async def reserve_seat(req: ReservationRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    # SELECT ... FOR UPDATE: concurrent requests for the same seat wait here one by one,
    # so only the first one can see it as available.
    seat = await db.scalar(select(Seat).where(Seat.id == req.seat_id).with_for_update())
    if seat is None:
        raise HTTPException(status_code=404, detail="Seat not found")

    if seat.status == SeatStatus.RESERVED:
        # A hold that has run out frees the seat right away, without waiting for the worker
        hold = await db.scalar(select(Reservation).where(Reservation.seat_id == seat.id).with_for_update())
        if hold is not None and hold.expires_at < utcnow():
            await db.execute(delete(Reservation).where(Reservation.id == hold.id))
            seat.status = SeatStatus.AVAILABLE

    if seat.status != SeatStatus.AVAILABLE:
        raise HTTPException(status_code=409, detail="Seat is already reserved or booked")

    seat.status = SeatStatus.RESERVED
    reservation = Reservation(user_id=user.id, seat_id=seat.id)
    db.add(reservation)
    await db.commit()
    await db.refresh(reservation)
    return reservation


async def own_hold(db: AsyncSession, reservation_id: int, user: User) -> Reservation:
    reservation = await db.scalar(
        select(Reservation)
        .where(Reservation.id == reservation_id, Reservation.user_id == user.id)
        .with_for_update()
    )
    if reservation is None:
        raise HTTPException(status_code=404, detail="Reservation not found")
    return reservation


@app.post(
    "/reservations/{reservation_id}/confirm",
    response_model=ReservationResponse,
    dependencies=[Depends(limit_reservations)],
)
async def confirm_booking(reservation_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    reservation = await own_hold(db, reservation_id, user)
    if reservation.status != SeatStatus.RESERVED:
        raise HTTPException(status_code=400, detail="This reservation is not on hold")
    if reservation.expires_at < utcnow():
        raise HTTPException(status_code=400, detail="The hold has expired. Please reserve the seat again.")

    reservation.status = SeatStatus.BOOKED
    seat = await db.get(Seat, reservation.seat_id, with_for_update=True)
    seat.status = SeatStatus.BOOKED
    await db.commit()
    await db.refresh(reservation)
    return reservation


@app.delete("/reservations/{reservation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_hold(reservation_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    reservation = await own_hold(db, reservation_id, user)
    if reservation.status != SeatStatus.RESERVED:
        raise HTTPException(status_code=400, detail="Only a seat on hold can be released")
    seat = await db.get(Seat, reservation.seat_id, with_for_update=True)
    seat.status = SeatStatus.AVAILABLE
    await db.delete(reservation)
    await db.commit()
