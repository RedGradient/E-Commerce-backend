from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Order, OrderItem, Product
from app.schemas.orders import (
    CancelOrderRequest,
    CancelOrderResponse,
    CheckoutResponse,
    OrderCreate,
    OrderItemCreate,
    OrderItemRead,
    OrderRead,
)
from app.services.cancellation import CancellationService
from app.services.checkout import CheckoutService
from app.session import get_db_session

router = APIRouter(prefix="/orders", tags=["orders"])


@router.get("/{order_id}", response_model=OrderRead)
async def get_order(order_id: int, session: AsyncSession = Depends(get_db_session)):
    order = await session.get(Order, order_id)
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="order not found"
        )
    return order


@router.post("", status_code=status.HTTP_201_CREATED, response_model=OrderRead)
async def create_order(
    payload: OrderCreate,
    session: AsyncSession = Depends(get_db_session),
):
    requested_product_ids = {i.product_id for i in payload.items}

    stmt = select(Product).where(Product.id.in_([i.product_id for i in payload.items]))
    products = {p.id: p for p in (await session.execute(stmt)).scalars().all()}

    missing_products = requested_product_ids - products.keys()
    if missing_products:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"missing product ids: {sorted(missing_products)}",
        )

    order = Order(
        items=[
            OrderItem(
                product_id=item.product_id,
                quantity=item.quantity,
                unit_price=products[item.product_id].price,
            )
            for item in payload.items
        ]
    )

    session.add(order)
    await session.commit()
    await session.refresh(order)

    return order


@router.post(
    "/{order_id}/items",
    status_code=status.HTTP_201_CREATED,
    response_model=OrderItemRead,
)
async def add_order_item(
    order_id: int,
    payload: OrderItemCreate,
    session: AsyncSession = Depends(get_db_session),
):
    order = await session.get(Order, order_id)
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="order not found",
        )

    product = await session.get(Product, payload.product_id)
    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="product not found",
        )

    order_item = OrderItem(
        order_id=order_id,
        product_id=payload.product_id,
        quantity=payload.quantity,
        unit_price=product.price,
    )

    session.add(order_item)
    await session.commit()
    await session.refresh(order_item)

    return order_item


@router.get(
    "/{order_id}/items/{item_id}",
    response_model=OrderItemRead,
)
async def get_order_item(
    order_id: int,
    item_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    stmt = select(OrderItem).where(
        OrderItem.id == item_id,
        OrderItem.order_id == order_id,
    )
    result = await session.execute(stmt)
    order_item = result.scalar_one_or_none()

    if order_item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="order item not found",
        )

    return order_item


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
