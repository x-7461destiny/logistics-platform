from app.models import Role, RoleEnum, User
from app.schemas.user import RoleName, UserCreate, UserResponse
from app.utils.auth import get_password_hash
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def create_user_service(user_data: UserCreate, db: AsyncSession) -> UserResponse:
    existing_user_result = await db.execute(
        select(User).where(User.email == user_data.email)
    )
    existing_user = existing_user_result.scalar_one_or_none()
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")

    hashed_password = get_password_hash(user_data.password)
    role_result = await db.execute(select(Role).where(Role.name == RoleEnum.user))
    role = role_result.scalar_one_or_none()
    new_user = User(
        email=user_data.email,
        password_hash=hashed_password,
        name=user_data.name,
        phone_number=user_data.phone_number,
        role_id=role.id if role else None,
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    return UserResponse(
        id=new_user.id,
        name=new_user.name,
        email=new_user.email,
        phone_number=new_user.phone_number,
        role=RoleName(role.name.value if role else RoleEnum.user.value),
        created_at=new_user.created_at,
    )


async def get_user_service(user_id: int, db: AsyncSession) -> UserResponse:
    result = await db.execute(
        select(User, Role.name).join(Role, User.role_id == Role.id).where(User.id == user_id)
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    user, role_name = row
    return UserResponse(
        id=user.id,
        name=user.name,
        email=user.email,
        phone_number=user.phone_number,
        role=RoleName(role_name.value),
        created_at=user.created_at,
    )
