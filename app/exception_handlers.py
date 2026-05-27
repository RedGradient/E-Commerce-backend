import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.domain.order_state_machine import InvalidOrderTransition
from app.logging_context import log_extra
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

logger = logging.getLogger(__name__)


def register_exception_handlers(app: FastAPI):
    @app.exception_handler(OrderNotFound)
    async def order_not_found_handler(
        request: Request, exc: OrderNotFound
    ) -> JSONResponse:
        logger.info(
            "Order not found",
            extra=log_extra(event="api.order.not_found", http_status=404),
        )
        return JSONResponse(status_code=404, content={"detail": "order not found"})

    @app.exception_handler(InvalidOrderTransition)
    async def invalid_order_transition_handler(
        request: Request, exc: InvalidOrderTransition
    ) -> JSONResponse:
        logger.warning(
            "Invalid order state transition",
            extra=log_extra(
                event="api.order.invalid_transition",
                http_status=409,
                order_status=exc.current.value,
                transition_event=exc.event.value,
            ),
            exc_info=exc,
        )
        return JSONResponse(
            status_code=409,
            content={
                "detail": (
                    f"order cannot apply {exc.event.value} "
                    f"in status {exc.current.value}"
                ),
            },
        )

    @app.exception_handler(OrderNotPayable)
    async def order_not_payable_handler(
        request: Request, exc: OrderNotPayable
    ) -> JSONResponse:
        logger.info(
            "Order not payable",
            extra=log_extra(event="api.order.not_payable", http_status=409),
        )
        return JSONResponse(status_code=409, content={"detail": "order not payable"})

    @app.exception_handler(PaymentFailed)
    async def payment_failed_handler(
        request: Request, exc: PaymentFailed
    ) -> JSONResponse:
        logger.error(
            "Payment provider failed",
            extra=log_extra(event="api.checkout.payment_failed", http_status=502),
            exc_info=exc.__cause__ or exc,
        )
        return JSONResponse(
            status_code=502, content={"detail": "payment provider failed"}
        )

    @app.exception_handler(IdempotencyInProgress)
    async def idempotency_in_progress_handler(
        request: Request, exc: IdempotencyInProgress
    ) -> JSONResponse:
        logger.info(
            "Checkout already in progress",
            extra=log_extra(event="api.checkout.in_progress", http_status=409),
        )
        return JSONResponse(
            status_code=409,
            content={"detail": "checkout request is already being processed"},
        )

    @app.exception_handler(OrderNotCancellable)
    async def order_not_cancellable_handler(
        request: Request, exc: OrderNotCancellable
    ) -> JSONResponse:
        logger.info(
            "Order not cancellable",
            extra=log_extra(event="api.order.not_cancellable", http_status=409),
        )
        return JSONResponse(
            status_code=409,
            content={"detail": "order cannot be cancelled in current status"},
        )

    @app.exception_handler(OrderAlreadyCancelled)
    async def order_already_cancelled_handler(
        request: Request, exc: OrderAlreadyCancelled
    ) -> JSONResponse:
        logger.info(
            "Order already cancelled",
            extra=log_extra(event="api.order.already_cancelled", http_status=409),
        )
        return JSONResponse(
            status_code=409,
            content={"detail": "order is already cancelled"},
        )

    @app.exception_handler(OrderNotRefundable)
    async def order_not_refundable_handler(
        request: Request, exc: OrderNotRefundable
    ) -> JSONResponse:
        logger.info(
            "Order not refundable",
            extra=log_extra(event="api.order.not_refundable", http_status=409),
        )
        return JSONResponse(
            status_code=409,
            content={"detail": "order cannot be refunded in current status"},
        )

    @app.exception_handler(OrderAlreadyRefunded)
    async def order_already_refunded_handler(
        request: Request, exc: OrderAlreadyRefunded
    ) -> JSONResponse:
        logger.info(
            "Order already refunded",
            extra=log_extra(event="api.order.already_refunded", http_status=409),
        )
        return JSONResponse(
            status_code=409,
            content={"detail": "order is already refunded"},
        )

    @app.exception_handler(RefundFailed)
    async def refund_failed_handler(
        request: Request, exc: RefundFailed
    ) -> JSONResponse:
        logger.error(
            "Payment provider refund failed",
            extra=log_extra(event="api.refund.failed", http_status=502),
            exc_info=exc.__cause__ or exc,
        )
        return JSONResponse(
            status_code=502,
            content={"detail": "payment provider refund failed"},
        )
