from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import HTTPException

from app.models import RoleEnum
from app.schemas.driver import DriverCreate
from app.schemas.user import RoleName, UserCreate
from app.services.drivers.driver_service import create_driver_service, get_driver_service
from app.services.users.user_service import create_user_service, get_user_service


async def populate_created_user(user):
    user.id = 1
    user.created_at = datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_create_user_success():
    role = SimpleNamespace(id=1, name=RoleEnum.user)
    role_result = Mock()
    role_result.scalar_one_or_none.return_value = role
    db = SimpleNamespace(
        execute=AsyncMock(return_value=role_result),
        add=Mock(),
        commit=AsyncMock(),
        refresh=AsyncMock(side_effect=populate_created_user),
    )

    user_data = UserCreate(
        email="test@example.com",
        name="Test User",
        phone_number="08012345678",
        password="securepassword",
        role=RoleName.user,
    )

    with patch("app.services.users.user_service.get_password_hash", return_value="hashed"):
        user = await create_user_service(user_data, db)

    assert user.email == user_data.email
    assert user.name == user_data.name
    assert user.phone_number == user_data.phone_number
    assert user.role == RoleName.user
    db.add.assert_called_once()
    db.commit.assert_awaited_once()
    db.refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_user_without_matching_role_uses_input_role():
    role_result = Mock()
    role_result.scalar_one_or_none.return_value = None
    db = SimpleNamespace(
        execute=AsyncMock(return_value=role_result),
        add=Mock(),
        commit=AsyncMock(),
        refresh=AsyncMock(side_effect=populate_created_user),
    )

    user_data = UserCreate(
        email="norole@example.com",
        name="No Role User",
        phone_number="08012345679",
        password="securepassword",
        role=RoleName.admin,
    )

    with patch("app.services.users.user_service.get_password_hash", return_value="hashed"):
        user = await create_user_service(user_data, db)

    assert user.role == RoleName.admin
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_user_by_id_success():
    user_record = SimpleNamespace(
        id=1,
        name="Fetch User",
        email="fetch@example.com",
        phone_number="08012345670",
        created_at=datetime.now(timezone.utc),
    )
    result = Mock()
    result.one_or_none.return_value = (user_record, RoleEnum.user)
    db = SimpleNamespace(execute=AsyncMock(return_value=result))

    fetched_user = await get_user_service(1, db)

    assert fetched_user.id == user_record.id
    assert fetched_user.email == user_record.email
    assert fetched_user.role == RoleName.user


@pytest.mark.asyncio
async def test_get_user_by_id_non_existent():
    result = Mock()
    result.one_or_none.return_value = None
    db = SimpleNamespace(execute=AsyncMock(return_value=result))

    with pytest.raises(HTTPException) as exc_info:
        await get_user_service(9999, db)

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "User not found"


@pytest.mark.asyncio
async def test_create_driver_success():
    db = SimpleNamespace(add=Mock(), commit=AsyncMock(), refresh=AsyncMock())
    driver_data = DriverCreate(
        email="driver@example.com",
        name="Test Driver",
        phone_number="08012345671",
        password="securepassword",
        vehicle_type="van",
    )

    driver = await create_driver_service(driver_data, db)

    assert driver.email == driver_data.email
    assert driver.name == driver_data.name
    assert driver.vehicle_type == driver_data.vehicle_type
    assert driver.is_available is True
    db.add.assert_called_once()
    db.commit.assert_awaited_once()
    db.refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_driver_by_id_success():
    driver_record = SimpleNamespace(id=1, email="fetchdriver@example.com")
    db = SimpleNamespace(get=AsyncMock(return_value=driver_record))

    fetched_driver = await get_driver_service(1, db)

    assert fetched_driver.id == driver_record.id
    assert fetched_driver.email == driver_record.email
    db.get.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_driver_by_id_non_existent():
    db = SimpleNamespace(get=AsyncMock(return_value=None))

    with pytest.raises(HTTPException) as exc_info:
        await get_driver_service(9999, db)

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Driver not found"
