"""数据模型 (SQLModel)。

设计为多账号预留：所有业务表都带 account_id。Phase 1 只有一行账号（从 .env 派生），
但不写死单账号常量。

数据最小化：不长期存完整正文，只存元数据 + AI 判断结果 + 必要短摘要。
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(SQLModel, table=True):
    """控制台登录用户。密码用 bcrypt 哈希存储。

    is_admin: 管理员可见全部账号并管理用户；普通用户只见自己名下账号。
    第一个注册/创建的用户自动成为管理员。
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True)
    password_hash: str
    is_admin: bool = Field(default=False)
    created_at: datetime = Field(default_factory=_utcnow)


class Account(SQLModel, table=True):
    """一个被监控的邮箱账号。Phase 1 只有一行。"""

    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(index=True, unique=True)
    # 归属的控制台用户（多租户隔离）；旧数据迁移时归给第一位管理员
    user_id: Optional[int] = Field(default=None, index=True, foreign_key="user.id")
    # INBOX 已处理到的最大 UID —— 重启后只拉取更大的 UID，避免重复处理旧邮件
    last_seen_uid: Optional[int] = Field(default=None)

    # --- Phase 2：绑定凭据（Fernet 加密后入库，绝不明文）---
    imap_auth_code_encrypted: Optional[str] = Field(default=None)

    # --- Phase 2：可在控制台配置的转发规则（为空则回退到 .env 默认）---
    forward_to: Optional[str] = Field(default=None)
    subject_prefix: Optional[str] = Field(default=None)
    importance_threshold: Optional[float] = Field(default=None)
    forward_interval_seconds: Optional[int] = Field(default=None)
    daily_forward_limit: Optional[int] = Field(default=None)
    enabled: bool = Field(default=True)

    # --- Phase 3：收信服务心跳（控制台据此判断服务是否在线）---
    last_poll_at: Optional[datetime] = Field(default=None)

    created_at: datetime = Field(default_factory=_utcnow)


class SenderRule(SQLModel, table=True):
    """发件人白/黑名单规则。pattern 为发件人地址的小写子串匹配。"""

    id: Optional[int] = Field(default=None, primary_key=True)
    account_id: int = Field(index=True, foreign_key="account.id")
    pattern: str                       # 小写子串，如 "boss@company.com" 或 "@company.com"
    kind: str                          # "whitelist"（必转发）| "blacklist"（必拦截）
    created_at: datetime = Field(default_factory=_utcnow)


class Event(SQLModel, table=True):
    """Phase 3：系统事件/告警（连接断开、转发失败、授权码失效、AI 限流等）。"""

    id: Optional[int] = Field(default=None, primary_key=True)
    account_id: Optional[int] = Field(default=None, index=True)
    level: str = Field(default="info")     # info | warning | error
    kind: str = Field(default="other")     # connection | auth | forward | ratelimit | other
    message: str = Field(default="")
    resolved: bool = Field(default=False)
    created_at: datetime = Field(default_factory=_utcnow)


class ProcessedEmail(SQLModel, table=True):
    """每封被处理过的邮件的记录，兼作幂等去重表。

    去重键：以 Message-ID 为逻辑唯一标识（UID 会随 UIDVALIDITY 变化，不可靠）。
    (account_id, message_id) 组合唯一。
    """

    __table_args__ = (UniqueConstraint("account_id", "message_id", name="uq_account_message"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    account_id: int = Field(index=True, foreign_key="account.id")
    message_id: str = Field(index=True)
    uid: Optional[str] = Field(default=None)

    # --- 邮件元数据（不含完整正文）---
    from_addr: str = Field(default="")
    subject: str = Field(default="")
    received_at: Optional[datetime] = Field(default=None)

    # --- 判断结果 ---
    prefiltered: bool = Field(default=False)   # True=被规则预筛拦下，未调用模型
    is_important: bool = Field(default=False)
    confidence: float = Field(default=0.0)
    reason: str = Field(default="")
    category: str = Field(default="")
    short_summary: str = Field(default="")     # 数据最小化：只存短摘要

    # --- 转发状态 ---
    forwarded: bool = Field(default=False)
    forwarded_at: Optional[datetime] = Field(default=None)
    error: str = Field(default="")

    # --- Phase 3：人工复核纠错（用户在控制台标记「其实重要/其实垃圾」）---
    review_label: Optional[str] = Field(default=None)   # important | not_important | None
    reviewed_at: Optional[datetime] = Field(default=None)

    created_at: datetime = Field(default_factory=_utcnow)
