"""FastAPI 依赖注入。"""

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import InvalidCredentialsError, PermissionDeniedError
from app.core.security import decode_access_token
from app.models.base import get_db
from app.models.user import User


async def get_current_user(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> User:
    """从 Authorization: Bearer <token> 解析当前用户。

    所有需要认证的端点都依赖此函数。
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise InvalidCredentialsError("缺少 Authorization header")

    token = authorization.removeprefix("Bearer ").strip()
    payload = decode_access_token(token)
    sub = payload.get("sub")
    if not sub:
        raise InvalidCredentialsError("token 缺少 subject")

    try:
        user_id = int(sub)
    except (TypeError, ValueError) as e:
        raise InvalidCredentialsError(f"无效的 subject: {sub}") from e

    user = await db.get(User, user_id)
    if user is None:
        raise InvalidCredentialsError("用户不存在")
    if not user.is_active:
        raise PermissionDeniedError("账号已被禁用")
    return user


# 重新导出方便其他模块统一导入
__all__ = ["get_db", "get_current_user", "settings"]
