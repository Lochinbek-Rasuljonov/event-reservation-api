import asyncio
import os

from celery import Celery
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool

from database import make_engine
from models import Reservation, Seat, SeatStatus, utcnow

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

celery_app = Celery("tasks", broker=REDIS_URL, backend=REDIS_URL)
celery_app.conf.timezone = "UTC"
celery_app.conf.beat_schedule = {
    "release-expired-holds-every-minute": {
        "task": "tasks.release_expired_reservations",
        "schedule": 60.0,
    },
}


async def release_expired_reservations(session: AsyncSession) -> int:
    """Delete holds whose time ran out and make their seats available again."""
    expired = (
        await session.scalars(
            select(Reservation)
            .where(Reservation.status == SeatStatus.RESERVED, Reservation.expires_at < utcnow())
            # Rows a request is already working on are left for the next run
            .with_for_update(skip_locked=True)
        )
    ).all()
    for reservation in expired:
        await session.execute(
            update(Seat)
            .where(Seat.id == reservation.seat_id, Seat.status == SeatStatus.RESERVED)
            .values(status=SeatStatus.AVAILABLE)
        )
        await session.delete(reservation)
    await session.commit()
    return len(expired)


async def _run_release() -> int:
    # Each task call runs in a fresh event loop, so it gets its own engine without a pool
    engine = make_engine(poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            return await release_expired_reservations(session)
    finally:
        await engine.dispose()


@celery_app.task(name="tasks.release_expired_reservations")
def release_expired_reservations_task() -> str:
    return f"Released {asyncio.run(_run_release())} expired holds"
