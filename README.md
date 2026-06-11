```
API (FastAPI)
  ├── Orders / Products / Webhooks / Metrics
  ├── Services: checkout, cancellation, refund, orders
  ├── Domain: order state machine (Created → Processing → Paid / Cancelled / Refunded)
  └── Outbox pattern → RabbitMQ

Workers:
  ├── outbox_publisher      — publish order.paid / cancelled / refunded
  ├── order_events_consumer — process events from RabbitMQ
  └── order_cancellator     — cancel stale Created orders
```

# E-Commerce Backend

[![Coverage](https://codecov.io/gh/RedGradient/E-Commerce-backend/branch/main/graph/badge.svg)](https://codecov.io/gh/RedGradient/E-Commerce-backend)

The project is an e-commerce backend that handles order payments with **Stripe**, domain events via the **transactional outbox**, and runs API and background workers in **Docker Compose**.

The project was built with a focus on production-style patterns: fixed order state transitions via a state machine, idempotent checkout, event-idempotent RabbitMQ consumer, webhook-driven updates, observability through metrics, and logging infrastructure.

---

## Quick start

```bash
cp .env.example .env
docker compose up --build
```

On the first run, Compose will automatically:

1. Apply database migrations  
2. Seed sample products  
3. Start the API, workers, and observability stack

When logs settle, open <http://localhost:8000/docs> — the API is ready to use.  
No Stripe account is required: .env.example uses PAYMENTS_PROVIDER=mock.

---

## What it does

- `POST /orders` **Create orders**
- `POST /orders/{id}/checkout` **Checkout** via Stripe PaymentIntent (`confirm=true` in the current integration)
- `POST /orders/{id}/cancel` **Cancel** orders in `Created` (through API or timeout worker)
- `POST /orders/{id}/refund` **Refund** paid orders via Stripe refund
- **Emit domain events** (`order.paid`, `order.cancelled`, `order.refunded`) to RabbitMQ after the database commit

Payment and refund **final state** is applied from **Stripe webhooks** (signature verification, idempotent handling). The API and workers update PostgreSQL; side effects are written to an **outbox** table and published asynchronously.

---

## Stack

- Python 3.12, FastAPI, asyncio
- PostgreSQL 16, Alembic migrations, SQLAlchemy 2 (async)
- Redis
- RabbitMQ
- Stripe API + webhooks
- Prometheus, Grafana
- Docker Compose

---

### Run the full stack

| Service | URL |
|---|---|
| API | <http://localhost:8000> |
| API docs | <http://localhost:8000/docs> |
| Grafana | <http://localhost:3000> (`admin` / `admin`) |
| Prometheus | <http://localhost:9090> |
| RabbitMQ UI | <http://localhost:15672> (`guest` / `guest`) |

---

## Background workers

| Worker | Module | Purpose |
|---|---|---|
| **outbox_publisher** | `app.workers.outbox_publisher` | Polls `outbox`, publishes to `order.events`, marks `published_at` |
| **order_events_consumer** | `app.workers.order_events_consumer` | Consumes `order.paid` / `order.cancelled` / `order.refunded` (logs; hook for digital fulfillment) |
| **order_cancellator** | `app.workers.order_cancellator` | `run_batch()` selects stale `Created` orders and calls `CancellationService` |

Cancellation timeout is configured in the worker as `STALE_ORDER_AFTER` (default `10` seconds in code).
