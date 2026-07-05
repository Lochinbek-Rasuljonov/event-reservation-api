# Real-Time Event Reservation & Ticketing API

A high-concurrency event ticketing and seat reservation API built with FastAPI, PostgreSQL, Redis, and Celery. 

This project implements row-level database locking to handle race conditions during high-concurrency seat reservation requests, alongside an asynchronous worker setup to auto-release expired reservation holds.

## Features
- **Concurrency Control**: Implements PostgreSQL row-level locking (`SELECT ... FOR UPDATE` via async SQLAlchemy) on the seat table to prevent double-booking of seats.
- **Asynchronous Auto-Release Hold**: Uses Celery Beat & Celery Workers with Redis as a message broker to scan for and release expired holds (seats left in 'reserved' status for >10 mins without payment confirmation).
- **JWT Authentication**: Secure user registration, login, and authorization routes.
- **Microservices Deployment**: Complete containerized multi-service orchestrator utilizing Docker and Docker Compose.

## System Architecture
```
                   +------------------+
                   |  FastAPI Client  |
                   +--------+---------+
                            |
         +------------------+------------------+
         |                                     |
         v                                     v
+--------+--------+                   +--------+--------+
|  FastAPI App    |                   |  Celery Beat    |
+--------+--------+                   +--------+--------+
         |                                     | (Trigger release hold)
         | (DB queries & locks)                v
         |                            +--------+--------+
         |                            |  Celery Worker  |
         |                            +--------+--------+
         |                                     |
         +------------------+------------------+
                            |
                            v
                  +---------+---------+
                  |  PostgreSQL / DB  |
                  +-------------------+
```

## API Endpoints
- `POST /register`: Registers a new user.
- `POST /token`: Authenticates a user and returns a JWT access token.
- `POST /events`: Creates an event and pre-populates its seats (Admin only).
- `GET /events`: Lists all events and their seats.
- `POST /reservations`: Creates a temporary 10-minute hold on a seat (utilizes row-level locking).
- `POST /reservations/{reservation_id}/confirm`: Finalizes seat purchase (converts state to `BOOKED`).

## Local Setup & Deployment

Ensure you have Docker and Docker Compose installed.

1. Clone the repository:
   ```bash
   git clone https://github.com/Lochinbek-Rasuljonov/event-reservation-api.git
   cd event-reservation-api
   ```

2. Run the environment:
   ```bash
   docker-compose up --build -d
   ```

   This command initializes:
   - PostgreSQL database on port `5432`
   - Redis message broker on port `6379`
   - FastAPI application server on port `8000`
   - Celery worker to run background tasks
   - Celery beat schedule manager to trigger periodic jobs
