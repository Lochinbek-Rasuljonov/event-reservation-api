# Real-Time Event Reservation API

[![tests](https://github.com/Lochinbek-Rasuljonov/event-reservation-api/actions/workflows/tests.yml/badge.svg)](https://github.com/Lochinbek-Rasuljonov/event-reservation-api/actions/workflows/tests.yml)

A seat reservation API for events, built with FastAPI, async SQLAlchemy 2.0, PostgreSQL, Redis and Celery. Its main job is to make sure two people can never end up with the same seat, even when they click at the same moment.

## How it works

- **No double booking.** Reserving a seat locks its row with `SELECT ... FOR UPDATE`. Concurrent requests for the same seat wait in line, and only the first one finds it available. A test sends 20 simultaneous requests for one seat and checks that exactly one succeeds.
- **Holds that expire.** A reservation holds the seat for 10 minutes while the user checks out. Celery Beat runs a worker task every minute that frees expired holds. If someone asks for a seat whose hold has already run out, the API frees it on the spot instead of waiting for the worker.
- **Rate limiting.** Reservation and confirmation requests are limited per client IP (10 per minute by default). The counter lives in Redis, so all API workers share it.
- **Auth.** Users sign up and log in with JWT access tokens. Passwords are hashed with bcrypt. Only admins, listed in `ADMIN_EMAILS`, can create events.

## API

| Method | Path | Who | What it does |
|---|---|---|---|
| `POST` | `/register` | anyone | Create an account |
| `POST` | `/token` | anyone | Log in (form fields `username`, `password`) and get a JWT |
| `POST` | `/events` | admin | Create an event with its seats |
| `GET` | `/events` | anyone | List events with their number of free seats |
| `GET` | `/events/{id}` | anyone | One event with every seat and its status |
| `POST` | `/reservations` | user | Hold a seat for 10 minutes |
| `POST` | `/reservations/{id}/confirm` | owner | Turn the hold into a booking |
| `DELETE` | `/reservations/{id}` | owner | Release a hold |
| `GET` | `/health` | anyone | Health check |

Interactive docs are at `http://localhost:8000/docs` once it runs.

## Run it

```bash
git clone https://github.com/Lochinbek-Rasuljonov/event-reservation-api.git
cd event-reservation-api
cp .env.example .env   # set SECRET_KEY and ADMIN_EMAILS
docker compose up --build
```

This starts PostgreSQL, Redis, the API on port 8000, a Celery worker and Celery Beat. Register with an address from `ADMIN_EMAILS` to get an admin account.

## Tests

The tests run against a real PostgreSQL and Redis, because row locks can't be tested on SQLite.

```bash
pip install -r requirements-dev.txt
TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/events_test \
TEST_REDIS_URL=redis://localhost:6379/15 pytest
```

GitHub Actions runs them on every push.

## Project layout

```
main.py        API routes
models.py      SQLAlchemy models: users, events, seats, reservations
schemas.py     Request and response models
security.py    Password hashing and JWT
ratelimit.py   Per-IP rate limit in Redis
tasks.py       Celery task that releases expired holds
tests/         API tests, including the concurrency test
```
