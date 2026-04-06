from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel


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


class UserRegister(UserCreate):
    pass


class UserLogin(BaseModel):
    email: str
    password: str


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
    sub: Optional[str] = None
    principal_id: Optional[int] = None
    principal_type: Optional[str] = None
    role: Optional[RoleName] = None
