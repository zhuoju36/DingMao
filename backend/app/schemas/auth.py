"""认证相关 Pydantic schemas。"""

from pydantic import BaseModel, EmailStr, Field

from app.models.user import UserRole


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=100)
    # 新建项目时的默认角色（用户级默认，每个项目仍可独立选择）
    default_role: UserRole = UserRole.SUPERVISOR


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # 秒


class UserResponse(BaseModel):
    id: int
    email: str
    full_name: str | None
    default_role: UserRole
    is_active: bool

    model_config = {"from_attributes": True}
