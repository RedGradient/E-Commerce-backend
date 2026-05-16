from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.models.models import OrderStatus

Quantity = Annotated[int, Field(gt=0)]
Money = Annotated[Decimal, Field(ge=0, max_digits=10, decimal_places=2)]


class OrderItemCreate(BaseModel):
    product_id: Annotated[int, Field(gt=0)]
    quantity: Quantity


class OrderCreate(BaseModel):
    items: Annotated[list[OrderItemCreate], Field(min_length=1)]


class OrderItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    quantity: int
    unit_price: Money
    total_price: Money


class OrderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    total_price: Money
    status: OrderStatus
    paid_at: datetime | None = None
    items: list[OrderItemRead]


class CheckoutResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    order_id: int
    payment_intent_id: str
    status: OrderStatus
    amount: Money
    currency: str
    paid_at: datetime | None = None


class CancelOrderRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=255)


class CancelOrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    order_id: int
    status: OrderStatus
    cancelled_at: datetime
    cancel_reason: str | None = None
