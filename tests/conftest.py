import os
import sys
from pathlib import Path

# Configure the app for tests before it is imported
os.environ.setdefault("DATABASE_URL", os.getenv("TEST_DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/events_test"))
os.environ.setdefault("REDIS_URL", os.getenv("TEST_REDIS_URL", "redis://localhost:6379/15"))
os.environ["DB_NULLPOOL"] = "1"
os.environ["ADMIN_EMAILS"] = "admin@example.com"
os.environ["RESERVATION_RATE_LIMIT"] = "1000"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402
import pytest  # noqa: E402

from database import Base, engine  # noqa: E402
from main import app, lifespan  # noqa: E402


@pytest.fixture
async def client():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    async with lifespan(app):
        await app.state.redis.flushdb()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


async def make_user(client, email, password="secret123"):
    r = await client.post("/register", json={"email": email, "password": password})
    assert r.status_code == 201, r.text
    r = await client.post("/token", data={"username": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def make_event(client, seats=3):
    admin = await make_user(client, "admin@example.com")
    r = await client.post(
        "/events",
        json={"title": "Concert", "date": "2026-12-01T19:00:00Z", "price": 10, "seat_count": seats},
        headers=admin,
    )
    assert r.status_code == 201, r.text
    return r.json()
