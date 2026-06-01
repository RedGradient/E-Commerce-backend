from fastapi import APIRouter, Depends, Header, Request
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


@router.get("/{order_id}", response_model=OrderRead)
async def get_order(
    order_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    service = OrderService()
    return await service.get_order(order_id, session)


@router.post("", status_code=201, response_model=OrderRead)
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
)
async def get_order_item(
    order_id: int,
    item_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    service = OrderService()
    return await service.get_order_item(order_id, item_id, session)


@router.post("/{order_id}/checkout", response_model=CheckoutResponse)
async def checkout_order(
    order_id: int,
    request: Request,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_db_session),
):
    checkout_service = CheckoutService(request.app.state.stripe)
    return await checkout_service.checkout(order_id, idempotency_key, session)


@router.post("/{order_id}/cancel", response_model=CancelOrderResponse)
async def cancel_order(
    order_id: int,
    payload: CancelOrderRequest,
    session: AsyncSession = Depends(get_db_session),
):
    service = CancellationService()
    return await service.cancel(order_id, session, payload.reason)


@router.post("/{order_id}/refund", response_model=RefundResponse, status_code=200)
async def order_refund(
    order_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    service = RefundService()
    return await service.refund(order_id, session)
