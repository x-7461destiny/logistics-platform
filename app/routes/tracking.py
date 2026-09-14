import logging

import h3
from app.dependencies import get_current_user, resolve_principal_from_token
from app.models import Driver, User
from app.services.communication.websocket_service import manager
from app.services.tracking.tracking_service import TrackingService
from db.database import get_db
from fastapi import APIRouter, Depends, WebSocket, status
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()

tracking_service = TrackingService(manager)


@router.websocket("/ws/{driver_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    driver_id: str,
    db: AsyncSession = Depends(get_db),
):
    auth_header = websocket.headers.get("Authorization")
    if not auth_header:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    try:
        token_type, token = auth_header.split()
    except ValueError:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    if token_type.lower() != "bearer":
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    principal = await resolve_principal_from_token(token, db)
    if not isinstance(principal, Driver):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await tracking_service.websocket_connection(
        websocket, driver_id, principal, db
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
