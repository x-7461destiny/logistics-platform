from typing import Optional

from app.models import Driver
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select


async def get_driver_from_db(driver_id: int, db: AsyncSession) -> Optional[Driver]:
    """
    Fetch the complete Driver object from the database.
    """
    result = await db.execute(select(Driver).filter(Driver.id == driver_id))
    return result.scalar_one_or_none()


async def assign_driver(driver_id: int, db: AsyncSession) -> Optional[Driver]:
    """
    Atomically claim a driver by flipping availability in the database.
    """
    result = await db.execute(
        update(Driver)
        .where(Driver.id == driver_id, Driver.is_available.is_(True))
        .values(is_available=False)
        .returning(Driver.id)
    )
    claimed_driver_id = result.scalar_one_or_none()
    if claimed_driver_id is None:
        return None

    return await get_driver_from_db(claimed_driver_id, db)
