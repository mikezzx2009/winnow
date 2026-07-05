"""认证工具：bcrypt 密码哈希 + 基于 session 的登录校验 + 注册输入校验。"""

from __future__ import annotations

import re
from typing import Optional

import bcrypt
from fastapi import HTTPException, Request, status

_USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,32}$")


def validate_username(username: str) -> Optional[str]:
    """合法返回 None，否则返回中文错误信息。"""
    if not _USERNAME_RE.match(username or ""):
        return "用户名需为 3-32 位字母、数字或下划线"
    return None


def validate_password(password: str) -> Optional[str]:
    """合法返回 None，否则返回中文错误信息。"""
    if len(password or "") < 8:
        return "密码至少 8 位"
    return None


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def require_login(request: Request) -> str:
    """FastAPI 依赖：要求已登录，返回用户名；未登录抛 401。"""
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录")
    return user
