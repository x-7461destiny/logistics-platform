from app.dependencies import get_current_admin, get_current_driver, get_db
from app.models import Driver
from app.schemas.driver import DriverCreate, DriverResponse
from app.services.drivers.driver_service import (create_driver_service,
                                                 get_driver_service)
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


@router.post("/drivers", response_model=DriverResponse, status_code=status.HTTP_201_CREATED)
async def create_driver(
    driver: DriverCreate,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_admin),
):
    return await create_driver_service(driver, db)


@router.get("/drivers/{driver_id}", response_model=DriverResponse)
async def get_driver(
    driver_id: int,
    db: AsyncSession = Depends(get_db),
    current_driver: Driver = Depends(get_current_driver),
):
    if current_driver.id != driver_id:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return await get_driver_service(driver_id, db)
