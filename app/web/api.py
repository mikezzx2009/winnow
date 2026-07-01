"""控制台 REST API（挂载在 /api 下）。除登录外均需已登录。

多账号：账号相关端点接受可选 ?account_id=，缺省用主账号（id 最小）。
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
from app.db import get_or_create_primary_account, session_scope
from app.events import HEARTBEAT_STALE_SECONDS, is_healthy
from app.models import Account, Event, ProcessedEmail, SenderRule, User
from app.runtime import runtime_config_for
from app.security import hash_password, require_login, verify_password

router = APIRouter()


def db_session():
    with session_scope() as s:
        yield s


def _primary_account(session: Session) -> Account:
    acc = get_or_create_primary_account(settings.email_126)
    return session.get(Account, acc.id)


def _resolve_account(session: Session, account_id: Optional[int]) -> Account:
    if account_id is not None:
        acc = session.get(Account, account_id)
        if acc is None:
            raise HTTPException(status_code=404, detail="账号不存在")
        return acc
    return _primary_account(session)


# ----------------------------- 认证 -----------------------------

class LoginIn(BaseModel):
    username: str
    password: str


@router.post("/auth/login")
def login(body: LoginIn, request: Request, session: Session = Depends(db_session)):
    user = session.exec(select(User).where(User.username == body.username)).first()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    request.session["user"] = user.username
    return {"username": user.username}


@router.post("/auth/logout")
def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@router.get("/auth/me")
def me(user: str = Depends(require_login)):
    return {"username": user}


# ----------------------------- 账号管理（多账号）-----------------------------

class EmailIn(BaseModel):
    email: str


@router.get("/accounts")
def list_accounts(_: str = Depends(require_login), session: Session = Depends(db_session)):
    _primary_account(session)  # 确保至少有一个账号
    accs = session.exec(select(Account).order_by(Account.id)).all()
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
    body: EmailIn, _: str = Depends(require_login), session: Session = Depends(db_session)
):
    email = body.email.strip()
    if not email:
        raise HTTPException(status_code=400, detail="邮箱不能为空")
    if session.exec(select(Account).where(Account.email == email)).first():
        raise HTTPException(status_code=400, detail="该邮箱账号已存在")
    acc = Account(email=email)
    session.add(acc)
    session.flush()
    return {"id": acc.id, "email": acc.email}


@router.delete("/accounts/{account_id}")
def delete_account(
    account_id: int, _: str = Depends(require_login), session: Session = Depends(db_session)
):
    total = session.exec(select(func.count()).select_from(Account)).one()
    if total <= 1:
        raise HTTPException(status_code=400, detail="至少保留一个账号")
    acc = session.get(Account, account_id)
    if acc is not None:
        for r in session.exec(select(SenderRule).where(SenderRule.account_id == account_id)).all():
            session.delete(r)
        for e in session.exec(select(Event).where(Event.account_id == account_id)).all():
            session.delete(e)
        for p in session.exec(select(ProcessedEmail).where(ProcessedEmail.account_id == account_id)).all():
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
    _: str = Depends(require_login),
    session: Session = Depends(db_session),
):
    acc = _resolve_account(session, account_id)
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
    _: str = Depends(require_login),
    session: Session = Depends(db_session),
):
    acc = _resolve_account(session, account_id)
    acc.email = body.email.strip()
    acc.imap_auth_code_encrypted = encrypt(body.auth_code.strip())  # Fernet 加密入库
    session.add(acc)
    return {"ok": True, "email": acc.email, "bound": True}


@router.put("/account/config")
def put_config(
    body: ConfigIn,
    account_id: Optional[int] = None,
    _: str = Depends(require_login),
    session: Session = Depends(db_session),
):
    acc = _resolve_account(session, account_id)
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
    _: str = Depends(require_login),
    session: Session = Depends(db_session),
):
    acc = _resolve_account(session, account_id)
    rules = session.exec(select(SenderRule).where(SenderRule.account_id == acc.id)).all()
    return [{"id": r.id, "pattern": r.pattern, "kind": r.kind} for r in rules]


@router.post("/rules")
def add_rule(
    body: RuleIn,
    account_id: Optional[int] = None,
    _: str = Depends(require_login),
    session: Session = Depends(db_session),
):
    if body.kind not in ("whitelist", "blacklist"):
        raise HTTPException(status_code=400, detail="kind 必须是 whitelist 或 blacklist")
    pattern = body.pattern.strip().lower()
    if not pattern:
        raise HTTPException(status_code=400, detail="pattern 不能为空")
    acc = _resolve_account(session, account_id)
    rule = SenderRule(account_id=acc.id, pattern=pattern, kind=body.kind)
    session.add(rule)
    session.flush()
    return {"id": rule.id, "pattern": rule.pattern, "kind": rule.kind}


@router.delete("/rules/{rule_id}")
def delete_rule(
    rule_id: int, _: str = Depends(require_login), session: Session = Depends(db_session)
):
    rule = session.get(SenderRule, rule_id)
    if rule is not None:
        session.delete(rule)
    return {"ok": True}


# ----------------------------- 处理日志 -----------------------------

@router.get("/logs")
def list_logs(
    account_id: Optional[int] = None,
    _: str = Depends(require_login),
    session: Session = Depends(db_session),
    limit: int = 50,
    offset: int = 0,
    q: Optional[str] = None,
    important: Optional[bool] = None,
    forwarded: Optional[bool] = None,
):
    acc = _resolve_account(session, account_id)
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
    log_id: int, body: ReviewIn, _: str = Depends(require_login),
    session: Session = Depends(db_session),
):
    rec = session.get(ProcessedEmail, log_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="记录不存在")
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
    _: str = Depends(require_login),
    session: Session = Depends(db_session),
):
    acc = _resolve_account(session, account_id)
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
    _: str = Depends(require_login),
    session: Session = Depends(db_session),
    limit: int = 50,
    unresolved_only: bool = False,
):
    acc = _resolve_account(session, account_id)
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
    event_id: int, _: str = Depends(require_login), session: Session = Depends(db_session)
):
    e = session.get(Event, event_id)
    if e is not None:
        e.resolved = True
        session.add(e)
    return {"ok": True}


@router.get("/status")
def service_status(
    account_id: Optional[int] = None,
    _: str = Depends(require_login),
    session: Session = Depends(db_session),
):
    acc = _resolve_account(session, account_id)
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


# ----------------------------- 用户管理（多用户）-----------------------------

class UserIn(BaseModel):
    username: str
    password: str


class PasswordIn(BaseModel):
    password: str


@router.get("/users")
def list_users(_: str = Depends(require_login), session: Session = Depends(db_session)):
    users = session.exec(select(User).order_by(User.id)).all()
    return [{"id": u.id, "username": u.username} for u in users]


@router.post("/users")
def create_user(
    body: UserIn, _: str = Depends(require_login), session: Session = Depends(db_session)
):
    username = body.username.strip()
    if not username or not body.password:
        raise HTTPException(status_code=400, detail="用户名和密码不能为空")
    if session.exec(select(User).where(User.username == username)).first():
        raise HTTPException(status_code=400, detail="用户名已存在")
    session.add(User(username=username, password_hash=hash_password(body.password)))
    return {"ok": True}


@router.post("/users/{user_id}/password")
def set_user_password(
    user_id: int, body: PasswordIn, _: str = Depends(require_login),
    session: Session = Depends(db_session),
):
    if not body.password:
        raise HTTPException(status_code=400, detail="密码不能为空")
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    user.password_hash = hash_password(body.password)
    session.add(user)
    return {"ok": True}


@router.delete("/users/{user_id}")
def delete_user(
    user_id: int,
    request: Request,
    _: str = Depends(require_login),
    session: Session = Depends(db_session),
):
    total = session.exec(select(func.count()).select_from(User)).one()
    if total <= 1:
        raise HTTPException(status_code=400, detail="至少保留一个用户")
    user = session.get(User, user_id)
    if user is None:
        return {"ok": True}
    if user.username == request.session.get("user"):
        raise HTTPException(status_code=400, detail="不能删除当前登录用户")
    session.delete(user)
    return {"ok": True}
