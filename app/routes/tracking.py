import logging

import h3
from app.dependencies import get_current_driver, get_current_user
from app.models import Driver, User
from app.services.communication.websocket_service import ConnectionManager
from app.services.tracking.tracking_service import TrackingService
from db.database import get_db
from fastapi import APIRouter, Depends, WebSocket
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()

manager = ConnectionManager()
tracking_service = TrackingService(manager)


@router.websocket("/ws/{driver_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    driver_id: str,
    current_driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
):
    await tracking_service.websocket_connection(
        websocket, driver_id, current_driver, db
    )


@router.get("/nearby-drivers")
async def get_nearby_drivers(
    lat: float,
    lng: float,
    initial_radius_km: float = 1,
    max_radius_km: float = 10,
    vehicle_type: str = "all",
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    nearby_drivers = await tracking_service.get_nearby_drivers(
        lat, lng, initial_radius_km, max_radius_km, vehicle_type
    )
    return nearby_drivers
