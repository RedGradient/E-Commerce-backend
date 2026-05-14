# Team Simulation: Round 2 — Order cancellation merge

You are the integration owner on branch `integration/mainline`.

## Situation

While you were improving checkout on `integration/mainline`, developer **Alex** finished branch `feature/order-cancellation` with:

- `POST /orders/{order_id}/cancel`
- `OrderStatus.Cancelled`
- fields `cancelled_at`, `cancel_reason`
- RabbitMQ event `order.cancelled`

Meanwhile on `integration/mainline` you already landed a hotfix:

- new status `OrderStatus.Processing` for checkout flow
- checkout now uses shared `app.state.stripe` singleton
- RabbitMQ constant `order.processing` (reserved for future use)

## Your tasks

1. Merge `feature/order-cancellation` into `integration/mainline`.
2. Resolve conflicts preserving:
   - **both** status values: `Processing` and `Cancelled`
   - cancellation endpoint and event publishing from Alex's branch
   - checkout improvements from integration (`app.state.stripe`, `Processing` step)
3. Update business rules after merge:
   - only `Created` orders can be cancelled
   - paid orders must **not** be cancellable via this endpoint
   - checkout must still work for `Created` orders
4. Run smoke tests:
   - create order → cancel → verify `Cancelled`
   - create order → checkout → verify `Paid`
   - try cancel paid order → expect `409`
5. Commit merge resolution with a clear message.

## Constraints

- No force push on shared branches.
- Do not delete Alex's cancellation service during conflict resolution.

## Hints

- Conflicts are expected in `app/models.py`, `app/routers/orders.py`, `app/schemas/orders.py`, `app/messaging.py`, `app/exception_handlers.py`.
- After merge you may need to recreate DB tables (`create_tables` script) because enum values changed.
