"""认证路由：注册 / 登录 / 当前用户。"""

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_current_user
from app.core.exceptions import AuthError, InvalidCredentialsError
from app.core.security import (
    create_access_token,
    hash_password,
    verify_password,
)
from app.models.base import get_db
from app.models.user import User
from app.schemas.auth import (
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    """注册新用户（邮箱唯一）。"""
    existing = await db.execute(select(User).where(User.email == req.email))
    if existing.scalar_one_or_none() is not None:
        raise AuthError(f"邮箱已被注册: {req.email}")

    user = User(
        email=req.email,
        hashed_password=hash_password(req.password),
        full_name=req.full_name,
        default_role=req.default_role.value,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)

    token = create_access_token(user.id)
    return TokenResponse(
        access_token=token,
        expires_in=settings.jwt_expire_minutes * 60,
    )


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    """邮箱+密码登录。"""
    result = await db.execute(select(User).where(User.email == req.email))
    user = result.scalar_one_or_none()

    if user is None or not verify_password(req.password, user.hashed_password):
        raise InvalidCredentialsError("邮箱或密码错误")
    if not user.is_active:
        raise AuthError("账号已被禁用")

    token = create_access_token(user.id)
    return TokenResponse(
        access_token=token,
        expires_in=settings.jwt_expire_minutes * 60,
    )


@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(get_current_user)) -> User:
    """当前用户信息。"""
    return current_user
