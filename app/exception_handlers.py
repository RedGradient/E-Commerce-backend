from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.services.cancellation import (
    OrderAlreadyCancelled,
    OrderNotCancellable,
)
from app.services.checkout import (
    IdempotencyInProgress,
    OrderNotFound,
    OrderNotPayable,
    PaymentFailed,
)
from app.services.refund import (
    OrderAlreadyRefunded,
    OrderNotRefundable,
    RefundFailed,
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

    @app.exception_handler(OrderNotCancellable)
    async def order_not_cancellable_handler(
        request: Request, exc: OrderNotCancellable
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"detail": "order cannot be cancelled in current status"},
        )

    @app.exception_handler(OrderAlreadyCancelled)
    async def order_already_cancelled_handler(
        request: Request, exc: OrderAlreadyCancelled
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"detail": "order is already cancelled"},
        )

    @app.exception_handler(OrderNotRefundable)
    async def order_not_refundable_handler(
        request: Request, exc: OrderNotRefundable
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"detail": "order cannot be refunded in current status"},
        )

    @app.exception_handler(OrderAlreadyRefunded)
    async def order_already_refunded_handler(
        request: Request, exc: OrderAlreadyRefunded
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"detail": "order is already refunded"},
        )

    @app.exception_handler(RefundFailed)
    async def refund_failed_handler(
        request: Request, exc: RefundFailed
    ) -> JSONResponse:
        return JSONResponse(
            status_code=502,
            content={"detail": "payment provider refund failed"},
        )
