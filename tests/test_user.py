from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import HTTPException

from app.models import Driver, RoleEnum, User
from app.schemas.driver import DriverCreate
from app.schemas.user import RoleName, UserCreate
from app.services.drivers.driver_service import create_driver_service, get_driver_service
from app.services.users.user_service import create_user_service, get_user_service
from app.utils.auth import authenticate_driver, authenticate_user, get_password_hash


async def populate_created_user(user):
    user.id = 1
    user.created_at = datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_create_user_success():
    role = SimpleNamespace(id=1, name=RoleEnum.user)
    empty_user_result = Mock()
    empty_user_result.scalar_one_or_none.return_value = None
    role_result = Mock()
    role_result.scalar_one_or_none.return_value = role
    db = SimpleNamespace(
        execute=AsyncMock(side_effect=[empty_user_result, role_result]),
        add=Mock(),
        commit=AsyncMock(),
        refresh=AsyncMock(side_effect=populate_created_user),
    )

    user_data = UserCreate(
        email="test@example.com",
        name="Test User",
        phone_number="08012345678",
        password="securepassword",
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
async def test_create_user_rejects_duplicate_email():
    existing_user = SimpleNamespace(id=1, email="test@example.com")
    existing_user_result = Mock()
    existing_user_result.scalar_one_or_none.return_value = existing_user
    db = SimpleNamespace(execute=AsyncMock(return_value=existing_user_result))

    user_data = UserCreate(
        email="test@example.com",
        name="Test User",
        phone_number="08012345678",
        password="securepassword",
    )

    with pytest.raises(HTTPException) as exc_info:
        await create_user_service(user_data, db)

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Email already registered"


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
    role = SimpleNamespace(id=2, name=RoleEnum.driver)
    empty_driver_result = Mock()
    empty_driver_result.scalar_one_or_none.return_value = None
    role_result = Mock()
    role_result.scalar_one_or_none.return_value = role
    db = SimpleNamespace(
        execute=AsyncMock(side_effect=[empty_driver_result, role_result]),
        add=Mock(),
        commit=AsyncMock(),
        refresh=AsyncMock(),
    )
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
    assert driver.role_id == role.id
    db.add.assert_called_once()
    db.commit.assert_awaited_once()
    db.refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_driver_rejects_duplicate_email():
    existing_driver = SimpleNamespace(id=1, email="driver@example.com")
    existing_driver_result = Mock()
    existing_driver_result.scalar_one_or_none.return_value = existing_driver
    db = SimpleNamespace(execute=AsyncMock(return_value=existing_driver_result))
    driver_data = DriverCreate(
        email="driver@example.com",
        name="Test Driver",
        phone_number="08012345671",
        password="securepassword",
        vehicle_type="van",
    )

    with pytest.raises(HTTPException) as exc_info:
        await create_driver_service(driver_data, db)

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Email already registered"


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


@pytest.mark.asyncio
async def test_authenticate_user_success():
    user = User(
        email="user@example.com",
        name="User",
        phone_number="08012345678",
        password_hash=get_password_hash("securepassword"),
    )
    result = Mock()
    result.scalar_one_or_none.return_value = user
    db = SimpleNamespace(execute=AsyncMock(return_value=result))

    authenticated_user = await authenticate_user(db, "user@example.com", "securepassword")

    assert authenticated_user is user


@pytest.mark.asyncio
async def test_authenticate_user_invalid_password():
    user = User(
        email="user@example.com",
        name="User",
        phone_number="08012345678",
        password_hash=get_password_hash("securepassword"),
    )
    result = Mock()
    result.scalar_one_or_none.return_value = user
    db = SimpleNamespace(execute=AsyncMock(return_value=result))

    authenticated_user = await authenticate_user(db, "user@example.com", "wrongpassword")

    assert authenticated_user is None


@pytest.mark.asyncio
async def test_authenticate_driver_success():
    driver = Driver(
        email="driver@example.com",
        name="Driver",
        phone_number="08012345671",
        password_hash=get_password_hash("securepassword"),
        vehicle_type="van",
    )
    result = Mock()
    result.scalar_one_or_none.return_value = driver
    db = SimpleNamespace(execute=AsyncMock(return_value=result))

    authenticated_driver = await authenticate_driver(db, "driver@example.com", "securepassword")

    assert authenticated_driver is driver
