from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.services.checkout import (
    IdempotencyInProgress,
    OrderNotFound,
    OrderNotPayable,
    PaymentFailed,
)


def register_exception_handlers(app: FastAPI):
    @app.exception_handler(OrderNotFound)
    async def order_not_found_handler(
        request: Request, exc: OrderNotFound
    ) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": "order not found"})

    @app.exception_handler(OrderNotPayable)
    async def order_not_payable_handler(
        request: Request, exc: OrderNotPayable
    ) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": "order not payable"})

    @app.exception_handler(PaymentFailed)
    async def payment_failed_handler(
        request: Request, exc: PaymentFailed
    ) -> JSONResponse:
        return JSONResponse(
            status_code=502, content={"detail": "payment provider failed"}
        )

    @app.exception_handler(IdempotencyInProgress)
    async def idempotency_in_progress_handler(
        request: Request, exc: IdempotencyInProgress
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"detail": "checkout request is already being processed"},
        )
