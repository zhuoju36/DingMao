"""认证核心：密码哈希 + JWT 编解码。"""

from datetime import UTC, datetime, timedelta
from typing import Any, cast

import bcrypt
from jose import JWTError, jwt

from app.core.config import settings
from app.core.exceptions import InvalidCredentialsError


def _to_bytes(s: str) -> bytes:
    """bcrypt 要求密码 <= 72 字节。超过则按规范截断（业界通用做法）。"""
    return s.encode("utf-8")[:72]


def hash_password(plain: str) -> str:
    """哈希明文密码。"""
    return bcrypt.hashpw(_to_bytes(plain), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """验证明文密码与哈希值是否匹配。"""
    try:
        return bcrypt.checkpw(_to_bytes(plain), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(subject: str | int, *, extra: dict[str, Any] | None = None) -> str:
    """生成 JWT access token。subject 通常是用户 id。"""
    now = datetime.now(UTC)
    expire = now + timedelta(minutes=settings.jwt_expire_minutes)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "iat": now,
        "exp": expire,
    }
    if extra:
        payload.update(extra)
    encoded = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return cast(str, encoded)


def decode_access_token(token: str) -> dict[str, Any]:
    """解码并验证 JWT token。失败抛 InvalidCredentialsError。"""
    try:
        return cast(
            dict[str, Any],
            jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]),
        )
    except JWTError as e:
        raise InvalidCredentialsError(f"无效或过期的 token: {e}") from e
