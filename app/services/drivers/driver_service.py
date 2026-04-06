from app.models import Driver, Role, RoleEnum
from app.schemas.driver import DriverCreate, DriverResponse
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.utils.auth import get_password_hash


async def create_driver_service(
    driver_data: DriverCreate, db: AsyncSession
) -> DriverResponse:
    existing_driver_result = await db.execute(
        select(Driver).where(Driver.email == driver_data.email)
    )
    existing_driver = existing_driver_result.scalar_one_or_none()
    if existing_driver:
        raise HTTPException(status_code=400, detail="Email already registered")

    role_result = await db.execute(select(Role).where(Role.name == RoleEnum.driver))
    role = role_result.scalar_one_or_none()
    hashed_password = get_password_hash(driver_data.password)
    new_driver = Driver(
        name=driver_data.name,
        email=driver_data.email,
        phone_number=driver_data.phone_number,
        password_hash=hashed_password,
        vehicle_type=driver_data.vehicle_type,
        is_available=True,
        role_id=role.id if role else None,
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
