"""控制台 REST API（挂载在 /api 下）。除登录外均需已登录。"""

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
from app.security import require_login, verify_password

router = APIRouter()


def db_session():
    with session_scope() as s:
        yield s


def _primary_account(session: Session) -> Account:
    acc = get_or_create_primary_account(settings.email_126)
    return session.get(Account, acc.id)


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


# ----------------------------- 账号 / 绑定 / 配置 -----------------------------

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
def get_account(_: str = Depends(require_login), session: Session = Depends(db_session)):
    acc = _primary_account(session)
    rc = runtime_config_for(acc, settings)
    return {
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
    body: BindingIn, _: str = Depends(require_login), session: Session = Depends(db_session)
):
    acc = _primary_account(session)
    acc.email = body.email.strip()
    acc.imap_auth_code_encrypted = encrypt(body.auth_code.strip())  # Fernet 加密入库
    session.add(acc)
    return {"ok": True, "email": acc.email, "bound": True}


@router.put("/account/config")
def put_config(
    body: ConfigIn, _: str = Depends(require_login), session: Session = Depends(db_session)
):
    acc = _primary_account(session)
    for field_name, value in body.model_dump(exclude_unset=True).items():
        setattr(acc, field_name, value)
    session.add(acc)
    return {"ok": True}


# ----------------------------- 发件人白/黑名单 -----------------------------

class RuleIn(BaseModel):
    pattern: str
    kind: str  # "whitelist" | "blacklist"


@router.get("/rules")
def list_rules(_: str = Depends(require_login), session: Session = Depends(db_session)):
    acc = _primary_account(session)
    rules = session.exec(select(SenderRule).where(SenderRule.account_id == acc.id)).all()
    return [{"id": r.id, "pattern": r.pattern, "kind": r.kind} for r in rules]


@router.post("/rules")
def add_rule(
    body: RuleIn, _: str = Depends(require_login), session: Session = Depends(db_session)
):
    if body.kind not in ("whitelist", "blacklist"):
        raise HTTPException(status_code=400, detail="kind 必须是 whitelist 或 blacklist")
    pattern = body.pattern.strip().lower()
    if not pattern:
        raise HTTPException(status_code=400, detail="pattern 不能为空")
    acc = _primary_account(session)
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
    _: str = Depends(require_login),
    session: Session = Depends(db_session),
    limit: int = 50,
    offset: int = 0,
    q: Optional[str] = None,
    important: Optional[bool] = None,
    forwarded: Optional[bool] = None,
):
    conditions = []
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
    """人工复核纠错：标记「其实重要 / 其实垃圾」，或清除标记。"""
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
def stats(_: str = Depends(require_login), session: Session = Depends(db_session)):
    day_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    def count(*conditions) -> int:
        stmt = select(func.count()).select_from(ProcessedEmail)
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
    _: str = Depends(require_login),
    session: Session = Depends(db_session),
    limit: int = 50,
    unresolved_only: bool = False,
):
    stmt = select(Event)
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
def service_status(_: str = Depends(require_login), session: Session = Depends(db_session)):
    acc = _primary_account(session)
    last_poll = acc.last_poll_at
    seconds = None
    if last_poll is not None:
        # SQLite 读回的 datetime 可能是 naive（代表 UTC），补上时区再比较
        lp = last_poll if last_poll.tzinfo else last_poll.replace(tzinfo=timezone.utc)
        seconds = (datetime.now(timezone.utc) - lp).total_seconds()

    def unresolved(level: str) -> int:
        return session.exec(
            select(func.count()).select_from(Event).where(
                Event.resolved == False, Event.level == level  # noqa: E712
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
