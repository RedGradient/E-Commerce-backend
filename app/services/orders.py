import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging_context import log_extra
from app.models.models import Order, OrderItem, Product
from app.schemas.orders import OrderCreate, OrderItemCreate

logger = logging.getLogger(__name__)


class OrderNotFound(Exception):
    def __init__(self, *args: object) -> None:
        super().__init__(*args)


class ProductNotFound(Exception):
    def __init__(self, *args: object) -> None:
        super().__init__(*args)


class ProductsNotFound(Exception):
    def __init__(self, product_ids: set[int]) -> None:
        self.product_ids = product_ids
        super().__init__(product_ids)


class OrderItemNotFound(Exception):
    def __init__(self, *args: object) -> None:
        super().__init__(*args)


class OrderService:
    async def get_order(self, order_id: int, session: AsyncSession) -> Order:
        order = await session.get(Order, order_id)
        if order is None:
            raise OrderNotFound()
        return order

    async def create_order(
        self,
        payload: OrderCreate,
        session: AsyncSession,
    ) -> Order:
        products = await self._load_products(
            session,
            [item.product_id for item in payload.items],
        )
        missing = {item.product_id for item in payload.items} - products.keys()
        if missing:
            raise ProductsNotFound(missing)

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

        logger.info(
            "Order created",
            extra=log_extra(event="order.created", order_id=order.id),
        )
        return order

    async def add_item(
        self,
        order_id: int,
        payload: OrderItemCreate,
        session: AsyncSession,
    ) -> OrderItem:
        await self.get_order(order_id, session)

        product = await session.get(Product, payload.product_id)
        if product is None:
            raise ProductNotFound()

        order_item = OrderItem(
            order_id=order_id,
            product_id=payload.product_id,
            quantity=payload.quantity,
            unit_price=product.price,
        )
        session.add(order_item)
        await session.commit()
        await session.refresh(order_item)

        logger.info(
            "Order item added",
            extra=log_extra(
                event="order.item_added",
                order_id=order_id,
                order_item_id=order_item.id,
            ),
        )
        return order_item

    async def get_order_item(
        self,
        order_id: int,
        item_id: int,
        session: AsyncSession,
    ) -> OrderItem:
        stmt = select(OrderItem).where(
            OrderItem.id == item_id,
            OrderItem.order_id == order_id,
        )
        order_item = (await session.execute(stmt)).scalar_one_or_none()
        if order_item is None:
            raise OrderItemNotFound()
        return order_item

    async def _load_products(
        self,
        session: AsyncSession,
        product_ids: list[int],
    ) -> dict[int, Product]:
        if not product_ids:
            return {}
        stmt = select(Product).where(Product.id.in_(product_ids))
        return {p.id: p for p in (await session.execute(stmt)).scalars().all()}
