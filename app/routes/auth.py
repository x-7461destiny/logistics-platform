from app.dependencies import get_current_driver, get_current_user, get_db
from app.schemas.driver import DriverCreate, DriverResponse
from app.schemas.user import RoleName, Token, UserRegister, UserResponse
from app.services.drivers.driver_service import create_driver_service
from app.services.users.user_service import create_user_service
from app.utils.auth import authenticate_driver, authenticate_user, create_access_token
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


@router.post("/auth/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register_user(
    user: UserRegister, db: AsyncSession = Depends(get_db)
):
    return await create_user_service(user, db)


@router.post("/auth/driver/register", response_model=DriverResponse, status_code=status.HTTP_201_CREATED)
async def register_driver(
    driver: DriverCreate, db: AsyncSession = Depends(get_db)
):
    return await create_driver_service(driver, db)


@router.post("/auth/token", response_model=Token)
async def login_user(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    user = await authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(
        data={
            "sub": user.email,
            "principal_id": user.id,
            "principal_type": "user",
            "role": user.role.name.value if user.role else "user",
        }
    )
    return Token(access_token=access_token)


@router.post("/auth/driver-token", response_model=Token)
async def login_driver(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    driver = await authenticate_driver(db, form_data.username, form_data.password)
    if not driver:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(
        data={
            "sub": driver.email,
            "principal_id": driver.id,
            "principal_type": "driver",
            "role": driver.role.name.value if driver.role else "driver",
        }
    )
    return Token(access_token=access_token)


@router.get("/auth/me", response_model=UserResponse)
async def get_me(current_user=Depends(get_current_user)):
    return UserResponse(
        id=current_user.id,
        name=current_user.name,
        email=current_user.email,
        phone_number=current_user.phone_number,
        role=RoleName(current_user.role.name.value if current_user.role else "user"),
        created_at=current_user.created_at,
    )


@router.get("/auth/driver-me", response_model=DriverResponse)
async def get_driver_me(current_driver=Depends(get_current_driver)):
    return DriverResponse(
        id=current_driver.id,
        name=current_driver.name,
        email=current_driver.email,
        phone_number=current_driver.phone_number,
        vehicle_type=current_driver.vehicle_type,
        is_available=current_driver.is_available,
    )
