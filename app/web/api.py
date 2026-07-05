"""控制台 REST API（挂载在 /api 下）。

多租户：每个控制台用户只能访问自己名下（Account.user_id）的账号及其数据；
管理员（is_admin）可见全部账号并独占用户管理。
账号相关端点接受可选 ?account_id=，缺省用当前用户的第一个账号。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import Session, desc, select

from app.config import settings
from app.crypto import encrypt
from app.db import claim_orphan_accounts, get_or_create_primary_account, session_scope
from app.events import HEARTBEAT_STALE_SECONDS, is_healthy
from app.models import Account, Event, ProcessedEmail, SenderRule, User
from app.runtime import runtime_config_for
from app.security import hash_password, validate_password, validate_username, verify_password

router = APIRouter()


def db_session():
    with session_scope() as s:
        yield s


def current_user(request: Request, session: Session = Depends(db_session)) -> User:
    """FastAPI 依赖：已登录用户（同请求内与端点共享同一 session）。"""
    username = request.session.get("user")
    if not username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录")
    user = session.exec(select(User).where(User.username == username)).first()
    if user is None:  # 用户已被删除但 cookie 还在
        request.session.clear()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录")
    return user


def admin_user(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    return user


def _resolve_account(session: Session, account_id: Optional[int], user: User) -> Account:
    """解析目标账号并做归属校验；缺省取当前用户的第一个账号。"""
    if account_id is not None:
        acc = session.get(Account, account_id)
        if acc is None or (not user.is_admin and acc.user_id != user.id):
            raise HTTPException(status_code=404, detail="账号不存在")
        return acc
    acc = session.exec(
        select(Account).where(Account.user_id == user.id).order_by(Account.id)
    ).first()
    if acc is None and user.is_admin:
        # 兼容旧单租户：管理员名下无账号时退回全局第一个
        acc = session.exec(select(Account).order_by(Account.id)).first()
    if acc is None:
        raise HTTPException(status_code=404, detail="尚未添加邮箱账号")
    return acc


def _owned_account(session: Session, account_id: Optional[int], user: User) -> Account:
    """按 id 取账号并校验归属（用于子资源的越权检查）。"""
    acc = session.get(Account, account_id) if account_id is not None else None
    if acc is None or (not user.is_admin and acc.user_id != user.id):
        raise HTTPException(status_code=404, detail="记录不存在")
    return acc


# ----------------------------- 认证 / 注册 -----------------------------

class LoginIn(BaseModel):
    username: str
    password: str


class RegisterIn(BaseModel):
    username: str
    password: str
    invite_code: Optional[str] = None


class SelfPasswordIn(BaseModel):
    old_password: str
    new_password: str


@router.get("/auth/config")
def auth_config():
    """公开端点：前端据此决定是否展示注册入口/邀请码输入框。"""
    return {
        "allow_registration": settings.allow_registration,
        "invite_required": bool(settings.registration_invite_code),
    }


@router.post("/auth/register")
def register(body: RegisterIn, request: Request, session: Session = Depends(db_session)):
    if not settings.allow_registration:
        raise HTTPException(status_code=403, detail="注册已关闭")
    if settings.registration_invite_code and body.invite_code != settings.registration_invite_code:
        raise HTTPException(status_code=400, detail="邀请码不正确")
    username = (body.username or "").strip()
    for err in (validate_username(username), validate_password(body.password)):
        if err:
            raise HTTPException(status_code=400, detail=err)
    if session.exec(select(User).where(User.username == username)).first():
        raise HTTPException(status_code=400, detail="用户名已存在")

    is_first = session.exec(select(func.count()).select_from(User)).one() == 0
    user = User(username=username, password_hash=hash_password(body.password), is_admin=is_first)
    session.add(user)
    session.flush()
    if is_first:
        # 第一位用户成为管理员，认领 CLI/.env 流程可能已创建的无归属账号
        session.commit()
        claim_orphan_accounts()
    request.session["user"] = user.username
    return {"username": user.username, "is_admin": user.is_admin}


@router.post("/auth/login")
def login(body: LoginIn, request: Request, session: Session = Depends(db_session)):
    user = session.exec(select(User).where(User.username == body.username)).first()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    request.session["user"] = user.username
    return {"username": user.username, "is_admin": user.is_admin}


@router.post("/auth/logout")
def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@router.get("/auth/me")
def me(user: User = Depends(current_user)):
    return {"username": user.username, "is_admin": user.is_admin}


@router.post("/auth/password")
def change_own_password(
    body: SelfPasswordIn, user: User = Depends(current_user), session: Session = Depends(db_session)
):
    if not verify_password(body.old_password, user.password_hash):
        raise HTTPException(status_code=400, detail="原密码不正确")
    err = validate_password(body.new_password)
    if err:
        raise HTTPException(status_code=400, detail=err)
    user.password_hash = hash_password(body.new_password)
    session.add(user)
    return {"ok": True}


# ----------------------------- 账号管理（多账号）-----------------------------

class EmailIn(BaseModel):
    email: str


@router.get("/accounts")
def list_accounts(user: User = Depends(current_user), session: Session = Depends(db_session)):
    if user.is_admin:
        total = session.exec(select(func.count()).select_from(Account)).one()
        if total == 0 and settings.email_126:
            # 兼容旧单租户首启：管理员首次打开时补建 .env 主账号
            get_or_create_primary_account(settings.email_126)
        stmt = select(Account).order_by(Account.id)
    else:
        stmt = select(Account).where(Account.user_id == user.id).order_by(Account.id)
    accs = session.exec(stmt).all()
    return [
        {
            "id": a.id,
            "email": a.email,
            "bound": a.imap_auth_code_encrypted is not None,
            "enabled": a.enabled,
        }
        for a in accs
    ]


@router.post("/accounts")
def create_account(
    body: EmailIn, user: User = Depends(current_user), session: Session = Depends(db_session)
):
    email = body.email.strip()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="请输入合法邮箱地址")
    if session.exec(select(Account).where(Account.email == email)).first():
        raise HTTPException(status_code=400, detail="该邮箱账号已存在")
    acc = Account(email=email, user_id=user.id)
    session.add(acc)
    session.flush()
    return {"id": acc.id, "email": acc.email}


@router.delete("/accounts/{account_id}")
def delete_account(
    account_id: int, user: User = Depends(current_user), session: Session = Depends(db_session)
):
    acc = _owned_account(session, account_id, user)
    for r in session.exec(select(SenderRule).where(SenderRule.account_id == acc.id)).all():
        session.delete(r)
    for e in session.exec(select(Event).where(Event.account_id == acc.id)).all():
        session.delete(e)
    for p in session.exec(
        select(ProcessedEmail).where(ProcessedEmail.account_id == acc.id)
    ).all():
        session.delete(p)
    session.delete(acc)
    return {"ok": True}


# ----------------------------- 账号绑定 / 配置 -----------------------------

class BindingIn(BaseModel):
    email: str
    auth_code: str


class ConfigIn(BaseModel):
    forward_to: Optional[str] = None
    subject_prefix: Optional[str] = None
    importance_threshold: Optional[float] = None
    forward_interval_seconds: Optional[int] = None
    daily_forward_limit: Optional[int] = None
    enabled: Optional[bool] = None


@router.get("/account")
def get_account(
    account_id: Optional[int] = None,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
):
    acc = _resolve_account(session, account_id, user)
    rc = runtime_config_for(acc, settings)
    return {
        "id": acc.id,
        "email": acc.email,
        "bound": acc.imap_auth_code_encrypted is not None,
        "enabled": acc.enabled,
        "forward_to": rc.forward_to,
        "subject_prefix": rc.subject_prefix,
        "importance_threshold": rc.importance_threshold,
        "forward_interval_seconds": rc.forward_interval_seconds,
        "daily_forward_limit": rc.daily_forward_limit,
    }


@router.put("/account/binding")
def put_binding(
    body: BindingIn,
    account_id: Optional[int] = None,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
):
    acc = _resolve_account(session, account_id, user)
    email = body.email.strip()
    other = session.exec(select(Account).where(Account.email == email)).first()
    if other is not None and other.id != acc.id:
        raise HTTPException(status_code=400, detail="该邮箱已被其它账号绑定")
    acc.email = email
    acc.imap_auth_code_encrypted = encrypt(body.auth_code.strip())  # Fernet 加密入库
    session.add(acc)
    return {"ok": True, "email": acc.email, "bound": True}


@router.put("/account/config")
def put_config(
    body: ConfigIn,
    account_id: Optional[int] = None,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
):
    acc = _resolve_account(session, account_id, user)
    for field_name, value in body.model_dump(exclude_unset=True).items():
        setattr(acc, field_name, value)
    session.add(acc)
    return {"ok": True}


# ----------------------------- 发件人白/黑名单 -----------------------------

class RuleIn(BaseModel):
    pattern: str
    kind: str  # "whitelist" | "blacklist"


@router.get("/rules")
def list_rules(
    account_id: Optional[int] = None,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
):
    acc = _resolve_account(session, account_id, user)
    rules = session.exec(select(SenderRule).where(SenderRule.account_id == acc.id)).all()
    return [{"id": r.id, "pattern": r.pattern, "kind": r.kind} for r in rules]


@router.post("/rules")
def add_rule(
    body: RuleIn,
    account_id: Optional[int] = None,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
):
    if body.kind not in ("whitelist", "blacklist"):
        raise HTTPException(status_code=400, detail="kind 必须是 whitelist 或 blacklist")
    pattern = body.pattern.strip().lower()
    if not pattern:
        raise HTTPException(status_code=400, detail="pattern 不能为空")
    acc = _resolve_account(session, account_id, user)
    rule = SenderRule(account_id=acc.id, pattern=pattern, kind=body.kind)
    session.add(rule)
    session.flush()
    return {"id": rule.id, "pattern": rule.pattern, "kind": rule.kind}


@router.delete("/rules/{rule_id}")
def delete_rule(
    rule_id: int, user: User = Depends(current_user), session: Session = Depends(db_session)
):
    rule = session.get(SenderRule, rule_id)
    if rule is not None:
        _owned_account(session, rule.account_id, user)  # 越权检查
        session.delete(rule)
    return {"ok": True}


# ----------------------------- 处理日志 -----------------------------

@router.get("/logs")
def list_logs(
    account_id: Optional[int] = None,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
    limit: int = 50,
    offset: int = 0,
    q: Optional[str] = None,
    important: Optional[bool] = None,
    forwarded: Optional[bool] = None,
):
    acc = _resolve_account(session, account_id, user)
    conditions = [ProcessedEmail.account_id == acc.id]
    if q:
        like = f"%{q}%"
        conditions.append(
            (ProcessedEmail.subject.like(like)) | (ProcessedEmail.from_addr.like(like))
        )
    if important is not None:
        conditions.append(ProcessedEmail.is_important == important)
    if forwarded is not None:
        conditions.append(ProcessedEmail.forwarded == forwarded)

    base = select(ProcessedEmail)
    count_stmt = select(func.count()).select_from(ProcessedEmail)
    for cond in conditions:
        base = base.where(cond)
        count_stmt = count_stmt.where(cond)

    total = session.exec(count_stmt).one()
    rows = session.exec(
        base.order_by(desc(ProcessedEmail.id)).offset(offset).limit(min(limit, 200))
    ).all()

    def serialize(r: ProcessedEmail) -> dict:
        return {
            "id": r.id,
            "from_addr": r.from_addr,
            "subject": r.subject,
            "category": r.category,
            "is_important": r.is_important,
            "confidence": r.confidence,
            "reason": r.reason,
            "prefiltered": r.prefiltered,
            "forwarded": r.forwarded,
            "error": r.error,
            "short_summary": r.short_summary,
            "review_label": r.review_label,
            "received_at": r.received_at.isoformat() if r.received_at else None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }

    return {"total": total, "items": [serialize(r) for r in rows]}


class ReviewIn(BaseModel):
    label: str  # important | not_important | clear


@router.post("/logs/{log_id}/review")
def review_log(
    log_id: int,
    body: ReviewIn,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
):
    rec = session.get(ProcessedEmail, log_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    _owned_account(session, rec.account_id, user)  # 越权检查
    if body.label == "clear":
        rec.review_label = None
        rec.reviewed_at = None
    elif body.label in ("important", "not_important"):
        rec.review_label = body.label
        rec.reviewed_at = datetime.now(timezone.utc)
    else:
        raise HTTPException(status_code=400, detail="label 必须是 important/not_important/clear")
    session.add(rec)
    return {"ok": True, "review_label": rec.review_label}


# ----------------------------- 统计面板 -----------------------------

@router.get("/stats")
def stats(
    account_id: Optional[int] = None,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
):
    acc = _resolve_account(session, account_id, user)
    day_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    scope = ProcessedEmail.account_id == acc.id

    def count(*conditions) -> int:
        stmt = select(func.count()).select_from(ProcessedEmail).where(scope)
        for cond in conditions:
            stmt = stmt.where(cond)
        return session.exec(stmt).one()

    today = ProcessedEmail.created_at >= day_start
    return {
        "today": {
            "received": count(today),
            "important": count(today, ProcessedEmail.is_important == True),  # noqa: E712
            "forwarded": count(today, ProcessedEmail.forwarded == True),  # noqa: E712
        },
        "total": {
            "received": count(),
            "important": count(ProcessedEmail.is_important == True),  # noqa: E712
            "forwarded": count(ProcessedEmail.forwarded == True),  # noqa: E712
        },
    }


# ----------------------------- 系统状态 / 告警 -----------------------------

@router.get("/events")
def list_events(
    account_id: Optional[int] = None,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
    limit: int = 50,
    unresolved_only: bool = False,
):
    acc = _resolve_account(session, account_id, user)
    stmt = select(Event).where(Event.account_id == acc.id)
    if unresolved_only:
        stmt = stmt.where(Event.resolved == False)  # noqa: E712
    rows = session.exec(stmt.order_by(desc(Event.id)).limit(min(limit, 200))).all()
    return [
        {
            "id": e.id,
            "level": e.level,
            "kind": e.kind,
            "message": e.message,
            "resolved": e.resolved,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in rows
    ]


@router.post("/events/{event_id}/resolve")
def resolve_event(
    event_id: int, user: User = Depends(current_user), session: Session = Depends(db_session)
):
    e = session.get(Event, event_id)
    if e is not None:
        _owned_account(session, e.account_id, user)  # 越权检查
        e.resolved = True
        session.add(e)
    return {"ok": True}


@router.get("/status")
def service_status(
    account_id: Optional[int] = None,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
):
    acc = _resolve_account(session, account_id, user)
    last_poll = acc.last_poll_at
    seconds = None
    if last_poll is not None:
        lp = last_poll if last_poll.tzinfo else last_poll.replace(tzinfo=timezone.utc)
        seconds = (datetime.now(timezone.utc) - lp).total_seconds()

    def unresolved(level: str) -> int:
        return session.exec(
            select(func.count()).select_from(Event).where(
                Event.account_id == acc.id, Event.resolved == False, Event.level == level  # noqa: E712
            )
        ).one()

    err = unresolved("error")
    return {
        "last_poll_at": last_poll.isoformat() if last_poll else None,
        "seconds_since_poll": int(seconds) if seconds is not None else None,
        "healthy": is_healthy(seconds, err),
        "stale_threshold": HEARTBEAT_STALE_SECONDS,
        "unresolved": {"error": err, "warning": unresolved("warning")},
        "bound": acc.imap_auth_code_encrypted is not None,
        "enabled": acc.enabled,
    }


# ----------------------------- 用户管理（仅管理员）-----------------------------

class UserIn(BaseModel):
    username: str
    password: str


class PasswordIn(BaseModel):
    password: str


@router.get("/users")
def list_users(_: User = Depends(admin_user), session: Session = Depends(db_session)):
    users = session.exec(select(User).order_by(User.id)).all()
    return [{"id": u.id, "username": u.username, "is_admin": u.is_admin} for u in users]


@router.post("/users")
def create_user(
    body: UserIn, _: User = Depends(admin_user), session: Session = Depends(db_session)
):
    username = (body.username or "").strip()
    for err in (validate_username(username), validate_password(body.password)):
        if err:
            raise HTTPException(status_code=400, detail=err)
    if session.exec(select(User).where(User.username == username)).first():
        raise HTTPException(status_code=400, detail="用户名已存在")
    session.add(User(username=username, password_hash=hash_password(body.password)))
    return {"ok": True}


@router.post("/users/{user_id}/password")
def set_user_password(
    user_id: int,
    body: PasswordIn,
    _: User = Depends(admin_user),
    session: Session = Depends(db_session),
):
    err = validate_password(body.password)
    if err:
        raise HTTPException(status_code=400, detail=err)
    target = session.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    target.password_hash = hash_password(body.password)
    session.add(target)
    return {"ok": True}


@router.delete("/users/{user_id}")
def delete_user(
    user_id: int,
    admin: User = Depends(admin_user),
    session: Session = Depends(db_session),
):
    target = session.get(User, user_id)
    if target is None:
        return {"ok": True}
    if target.id == admin.id:
        raise HTTPException(status_code=400, detail="不能删除当前登录用户")
    # 该用户名下的账号一并归给操作的管理员（避免数据变成无主孤儿）
    for acc in session.exec(select(Account).where(Account.user_id == target.id)).all():
        acc.user_id = admin.id
        session.add(acc)
    session.delete(target)
    return {"ok": True}