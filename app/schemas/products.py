from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class ProductCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: Annotated[str, Field(max_length=15)]


# Quantity = Annotated[int, Field(gt=0)]
# Price = Annotated[Decimal, Field(ge=0, max_digits=10, decimal_places=2)]

# class OrderItemCreate(BaseModel):
#     product_id: Annotated[int, Field(gt=0)]
#     quantity: Quantity

# class OrderCreate(BaseModel):
#     items: Annotated[list[OrderItemCreate], Field(min_length=1)]


# class OrderItemRead(BaseModel):
#     model_config = ConfigDict(from_attributes=True)

#     id: int
#     product_id: int
#     quantity: int
#     unit_price: Price
#     total_price: Price # (= quantity * unit_price)

# class OrderRead(BaseModel):
#     model_config = ConfigDict(from_attributes=True)

#     id: int
#     created_at: datetime
#     total_price: Price
#     items: list[OrderItemRead]
