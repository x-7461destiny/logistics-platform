from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class RoleName(str, Enum):
    admin = "admin"
    user = "user"
    driver = "driver"


class UserBase(BaseModel):
    name: str
    email: str
    phone_number: str


class UserCreate(UserBase):
    password: str
    role: RoleName = RoleName.user


class UserResponse(UserBase):
    id: int
    role: RoleName
    created_at: datetime

    class Config:
        orm_mode = True


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    user_id: Optional[int] = None
    role: Optional[RoleName] = None
