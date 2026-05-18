from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Product
from app.schemas.products import ProductCreate
from app.session import get_db_session

router = APIRouter(prefix="/products", tags=["products"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_product(
    payload: ProductCreate,
    session: AsyncSession = Depends(get_db_session),
):
    product = Product(name=payload.name)

    session.add(product)
    await session.commit()
    await session.refresh(product)

    return product
