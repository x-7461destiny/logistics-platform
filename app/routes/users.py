from app.dependencies import get_db
from app.schemas.user import UserCreate, UserResponse
from app.services.users.user_service import (create_user_service,
                                             get_user_service)
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


@router.post("/users", response_model=UserResponse)
async def create_user(user: UserCreate, db: AsyncSession = Depends(get_db)):
    return await create_user_service(user, db)


@router.get("/users/{user_id}", response_model=UserResponse)
async def get_user(user_id: int, db: AsyncSession = Depends(get_db)):
    return await get_user_service(user_id, db)
