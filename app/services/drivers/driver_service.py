from app.models import Driver
from app.schemas.driver import DriverCreate, DriverResponse
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.utils.auth import get_password_hash


async def create_driver_service(
    driver_data: DriverCreate, db: AsyncSession
) -> DriverResponse:
    hashed_password = get_password_hash(driver_data.password)
    new_driver = Driver(
        name=driver_data.name,
        email=driver_data.email,
        phone_number=driver_data.phone_number,
        password_hash=hashed_password,
        vehicle_type=driver_data.vehicle_type,
        is_available=True,
    )
    db.add(new_driver)
    await db.commit()
    await db.refresh(new_driver)
    return new_driver


async def get_driver_service(driver_id: int, db: AsyncSession) -> DriverResponse:
    driver = await db.get(Driver, driver_id)
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    return driver
