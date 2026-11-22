import asyncio

from sqlalchemy import update

from conftest import make_event, make_user
from database import async_session
from models import Reservation, utcnow
from tasks import release_expired_reservations


async def test_register_login_and_duplicate_email(client):
    await make_user(client, "a@example.com")
    r = await client.post("/register", json={"email": "A@example.com", "password": "secret123"})
    assert r.status_code == 400
    r = await client.post("/token", data={"username": "a@example.com", "password": "wrong-pass"})
    assert r.status_code == 400


async def test_password_rules(client):
    assert (await client.post("/register", json={"email": "b@example.com", "password": "short"})).status_code == 422
    too_long = "x" * 73
    assert (await client.post("/register", json={"email": "b@example.com", "password": too_long})).status_code == 422


async def test_only_admins_create_events(client):
    user = await make_user(client, "user@example.com")
    body = {"title": "Talk", "date": "2026-12-01T19:00:00", "price": 0, "seat_count": 2}
    assert (await client.post("/events", json=body)).status_code == 401
    assert (await client.post("/events", json=body, headers=user)).status_code == 403


async def test_create_list_and_get_event(client):
    event = await make_event(client, seats=3)
    assert [s["seat_number"] for s in event["seats"]] == ["Seat-0001", "Seat-0002", "Seat-0003"]
    assert event["available_seats"] == 3

    listed = (await client.get("/events")).json()
    assert listed[0]["id"] == event["id"] and listed[0]["available_seats"] == 3
    assert (await client.get(f"/events/{event['id']}")).json()["seats"] == event["seats"]
    assert (await client.get("/events/999")).status_code == 404


async def test_twenty_users_race_for_one_seat(client):
    seat_id = (await make_event(client))["seats"][0]["id"]
    users = [await make_user(client, f"u{i}@example.com") for i in range(20)]

    responses = await asyncio.gather(
        *(client.post("/reservations", json={"seat_id": seat_id}, headers=u) for u in users)
    )

    codes = sorted(r.status_code for r in responses)
    assert codes == [201] + [409] * 19


async def test_confirm_and_cancel(client):
    seats = (await make_event(client))["seats"]
    alice = await make_user(client, "alice@example.com")
    bob = await make_user(client, "bob@example.com")

    hold = (await client.post("/reservations", json={"seat_id": seats[0]["id"]}, headers=alice)).json()
    assert (await client.post(f"/reservations/{hold['id']}/confirm", headers=bob)).status_code == 404
    booked = await client.post(f"/reservations/{hold['id']}/confirm", headers=alice)
    assert booked.status_code == 200 and booked.json()["status"] == "booked"
    assert (await client.delete(f"/reservations/{hold['id']}", headers=alice)).status_code == 400

    hold2 = (await client.post("/reservations", json={"seat_id": seats[1]["id"]}, headers=alice)).json()
    assert (await client.delete(f"/reservations/{hold2['id']}", headers=alice)).status_code == 204
    again = await client.post("/reservations", json={"seat_id": seats[1]["id"]}, headers=bob)
    assert again.status_code == 201


async def expire_all_holds():
    async with async_session() as session:
        await session.execute(update(Reservation).values(expires_at=utcnow().replace(year=2000)))
        await session.commit()


async def test_expired_hold_cannot_be_confirmed_and_is_released(client):
    seat_id = (await make_event(client))["seats"][0]["id"]
    alice = await make_user(client, "alice@example.com")
    hold = (await client.post("/reservations", json={"seat_id": seat_id}, headers=alice)).json()
    await expire_all_holds()

    assert (await client.post(f"/reservations/{hold['id']}/confirm", headers=alice)).status_code == 400

    async with async_session() as session:
        assert await release_expired_reservations(session) == 1
    event = (await client.get("/events")).json()[0]
    assert event["available_seats"] == 3


async def test_expired_hold_frees_the_seat_without_the_worker(client):
    seat_id = (await make_event(client))["seats"][0]["id"]
    alice = await make_user(client, "alice@example.com")
    bob = await make_user(client, "bob@example.com")
    await client.post("/reservations", json={"seat_id": seat_id}, headers=alice)
    assert (await client.post("/reservations", json={"seat_id": seat_id}, headers=bob)).status_code == 409

    await expire_all_holds()
    assert (await client.post("/reservations", json={"seat_id": seat_id}, headers=bob)).status_code == 201


async def test_rate_limit_per_ip(client, monkeypatch):
    monkeypatch.setenv("RESERVATION_RATE_LIMIT", "3")
    seats = (await make_event(client, seats=5))["seats"]
    user = await make_user(client, "user@example.com")

    codes = [
        (await client.post("/reservations", json={"seat_id": s["id"]}, headers=user)).status_code
        for s in seats[:4]
    ]
    assert codes == [201, 201, 201, 429]
