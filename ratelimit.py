"""Fixed-window rate limit per client IP, counted in Redis so every API worker shares it."""
import os
import time

from fastapi import HTTPException, Request, status


async def limit_reservations(request: Request) -> None:
    limit = int(os.getenv("RESERVATION_RATE_LIMIT", "10"))
    window = int(os.getenv("RESERVATION_RATE_WINDOW", "60"))
    if limit <= 0:
        return
    ip = request.client.host if request.client else "unknown"
    key = f"ratelimit:reservations:{ip}:{int(time.time() // window)}"
    redis = request.app.state.redis
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, window)
    if count > limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many reservation attempts. Please try again shortly.",
            headers={"Retry-After": str(window)},
        )
