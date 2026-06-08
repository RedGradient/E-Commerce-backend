from fastapi import APIRouter, Depends, Header, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.orders import (
    CancelOrderRequest,
    CancelOrderResponse,
    CheckoutResponse,
    OrderCreate,
    OrderItemCreate,
    OrderItemRead,
    OrderRead,
    RefundResponse,
)
from app.services.cancellation import CancellationService
from app.services.checkout import CheckoutService
from app.services.orders import OrderService
from app.services.refund import RefundService
from app.session import get_db_session

router = APIRouter(prefix="/orders", tags=["orders"])

_ERROR_JSON = {
    "type": "object",
    "properties": {"detail": {"type": "string"}},
    "required": ["detail"],
}


@router.get(
    "/{order_id}",
    response_model=OrderRead,
    summary="Get order",
    description=(
        "Returns the current order state, including items and timestamps.\n\n"
        "Use this endpoint after checkout to check when the order becomes `Paid`."
    ),
    responses={
        status.HTTP_404_NOT_FOUND: {
            "description": "Order not found",
            "content": {
                "application/json": {
                    "schema": _ERROR_JSON,
                    "example": {"detail": "order not found"},
                }
            },
        },
    },
)
async def get_order(
    order_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    service = OrderService()
    return await service.get_order(order_id, session)


@router.post(
    "",
    status_code=201,
    response_model=OrderRead,
    summary="Create order",
    description=(
        "Creates a new order with one or more items.\n\n"
        "Products must already exist. Unit prices are snapshotted from the "
        "product catalog at creation time."
    ),
    responses={
        status.HTTP_404_NOT_FOUND: {
            "description": "One or more product IDs were not found",
            "content": {
                "application/json": {
                    "schema": _ERROR_JSON,
                    "example": {"detail": "missing product ids: [4, 5]"},
                }
            },
        },
    },
)
async def create_order(
    payload: OrderCreate,
    session: AsyncSession = Depends(get_db_session),
):
    service = OrderService()
    return await service.create_order(payload, session)


@router.post(
    "/{order_id}/items",
    status_code=201,
    response_model=OrderItemRead,
    summary="Add item to order",
    description=(
        "Adds a product line to an existing order.\n\n"
        "The product unit price is snapshotted at the moment the item is added."
    ),
    responses={
        status.HTTP_404_NOT_FOUND: {
            "description": "Order or product not found",
            "content": {
                "application/json": {
                    "schema": _ERROR_JSON,
                    "examples": {
                        "order_not_found": {
                            "summary": "Order does not exist",
                            "value": {"detail": "order not found"},
                        },
                        "product_not_found": {
                            "summary": "Product does not exist",
                            "value": {"detail": "product not found"},
                        },
                    },
                }
            },
        },
    },
)
async def add_order_item(
    order_id: int,
    payload: OrderItemCreate,
    session: AsyncSession = Depends(get_db_session),
):
    service = OrderService()
    return await service.add_item(order_id, payload, session)


@router.get(
    "/{order_id}/items/{item_id}",
    response_model=OrderItemRead,
    summary="Get order item",
    description="Returns a single order item that belongs to the given order.",
    responses={
        status.HTTP_404_NOT_FOUND: {
            "description": "Order item not found",
            "content": {
                "application/json": {
                    "schema": _ERROR_JSON,
                    "example": {"detail": "order item not found"},
                }
            },
        },
    },
)
async def get_order_item(
    order_id: int,
    item_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    service = OrderService()
    return await service.get_order_item(order_id, item_id, session)


@router.post(
    "/{order_id}/checkout",
    response_model=CheckoutResponse,
    summary="Start payment for order",
    description=(
        "Starts payment for an order in `Created` status.\n\n"
        "The response usually contains `Processing` and a `payment_intent_id`. "
        "Final `Paid` status is applied asynchronously via Stripe webhook.\n\n"
        "In mock mode (`PAYMENTS_PROVIDER=mock`), the webhook is sent automatically."
    ),
    responses={
        status.HTTP_404_NOT_FOUND: {
            "description": "Order not found",
            "content": {
                "application/json": {
                    "schema": _ERROR_JSON,
                    "example": {"detail": "order not found"},
                }
            },
        },
        status.HTTP_409_CONFLICT: {
            "description": "Checkout cannot be completed",
            "content": {
                "application/json": {
                    "schema": _ERROR_JSON,
                    "examples": {
                        "not_payable": {
                            "summary": "Order is not in Created status",
                            "value": {"detail": "order not payable"},
                        },
                        "in_progress": {
                            "summary": "Same Idempotency-Key is already processing",
                            "value": {
                                "detail": "checkout request is already being processed"
                            },
                        },
                    },
                }
            },
        },
        status.HTTP_502_BAD_GATEWAY: {
            "description": "Payment provider failed",
            "content": {
                "application/json": {
                    "schema": _ERROR_JSON,
                    "example": {"detail": "payment provider failed"},
                }
            },
        },
    },
)
async def checkout_order(
    order_id: int,
    request: Request,
    idempotency_key: str = Header(
        alias="Idempotency-Key",
        description=(
            "Unique key for safe retries. Repeat the request with the same key "
            "to receive the cached checkout result."
        ),
        example="checkout-order-1",
    ),
    session: AsyncSession = Depends(get_db_session),
):
    checkout_service = CheckoutService(request.app.state.stripe)
    return await checkout_service.checkout(order_id, idempotency_key, session)


@router.post(
    "/{order_id}/cancel",
    response_model=CancelOrderResponse,
    summary="Cancel order",
    description=(
        "Cancels an order in `Created` status.\n\n"
        "An `order.cancelled` domain event is written to the outbox after commit."
    ),
    responses={
        status.HTTP_404_NOT_FOUND: {
            "description": "Order not found",
            "content": {
                "application/json": {
                    "schema": _ERROR_JSON,
                    "example": {"detail": "order not found"},
                }
            },
        },
        status.HTTP_409_CONFLICT: {
            "description": "Cancellation is not allowed",
            "content": {
                "application/json": {
                    "schema": _ERROR_JSON,
                    "examples": {
                        "not_cancellable": {
                            "summary": "Order is not in Created status",
                            "value": {
                                "detail": "order cannot be cancelled in current status"
                            },
                        },
                        "already_cancelled": {
                            "summary": "Order was already cancelled",
                            "value": {"detail": "order is already cancelled"},
                        },
                    },
                }
            },
        },
    },
)
async def cancel_order(
    order_id: int,
    payload: CancelOrderRequest,
    session: AsyncSession = Depends(get_db_session),
):
    service = CancellationService()
    return await service.cancel(order_id, session, payload.reason)


@router.post(
    "/{order_id}/refund",
    response_model=RefundResponse,
    status_code=200,
    summary="Refund paid order",
    description=(
        "Starts a refund for an order in `Paid` status.\n\n"
        "The response confirms that the refund was initiated. "
        "Final `Refunded` status is applied asynchronously via Stripe webhook."
    ),
    responses={
        status.HTTP_404_NOT_FOUND: {
            "description": "Order not found",
            "content": {
                "application/json": {
                    "schema": _ERROR_JSON,
                    "example": {"detail": "order not found"},
                }
            },
        },
        status.HTTP_409_CONFLICT: {
            "description": "Refund is not allowed",
            "content": {
                "application/json": {
                    "schema": _ERROR_JSON,
                    "examples": {
                        "not_refundable": {
                            "summary": "Order is not in Paid status",
                            "value": {
                                "detail": "order cannot be refunded in current status"
                            },
                        },
                        "already_refunded": {
                            "summary": "Order was already refunded",
                            "value": {"detail": "order is already refunded"},
                        },
                    },
                }
            },
        },
        status.HTTP_502_BAD_GATEWAY: {
            "description": "Payment provider refund failed",
            "content": {
                "application/json": {
                    "schema": _ERROR_JSON,
                    "example": {"detail": "payment provider refund failed"},
                }
            },
        },
    },
)
async def order_refund(
    order_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    service = RefundService()
    return await service.refund(order_id, session)
