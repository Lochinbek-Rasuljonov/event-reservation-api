from celery import Celery
from database import async_session
from sqlalchemy import select, update
from models import Reservation, Seat, SeatStatus
from datetime import datetime
import asyncio

celery_app = Celery("tasks", broker="redis://redis:6379/0", backend="redis://redis:6379/0")

# Periodic task configuration
celery_app.conf.beat_schedule = {
    "release-expired-holds-every-minute": {
        "task": "tasks.release_expired_reservations_task",
        "schedule": 60.0,
    },
}

@celery_app.task
def release_expired_reservations_task():
    loop = asyncio.get_event_loop()
    if loop.is_closed():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    loop.run_until_complete(release_expired_reservations())

async def release_expired_reservations():
    async with async_session() as session:
        now = datetime.utcnow()
        # Find active holds (RESERVED) that have passed their expires_at time
        query = select(Reservation).where(
            Reservation.expires_at < now,
            Reservation.is_active == SeatStatus.RESERVED
        )
        result = await session.execute(query)
        expired = result.scalars().all()
        
        if not expired:
            return f"No expired reservations found at {now}"

        for reservation in expired:
            # Mark reservation as inactive/available (or delete it)
            await session.delete(reservation)
            
            # Reset seat back to AVAILABLE
            await session.execute(
                update(Seat)
                .where(Seat.id == reservation.seat_id)
                .values(status=SeatStatus.AVAILABLE)
            )
        
        await session.commit()
        return f"Successfully released {len(expired)} reservations at {now}"
