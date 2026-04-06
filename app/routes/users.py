from app.dependencies import get_current_user, get_db
from app.models import RoleEnum, User
from app.schemas.user import UserCreate, UserResponse
from app.services.users.user_service import (create_user_service,
                                             get_user_service)
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


@router.post("/users", response_model=UserResponse)
async def create_user(user: UserCreate, db: AsyncSession = Depends(get_db)):
    return await create_user_service(user, db)


@router.get("/users/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user = await get_user_service(user_id, db)
    current_role = current_user.role.name if current_user.role else None
    if current_user.id != user_id and current_role != RoleEnum.admin:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return user
