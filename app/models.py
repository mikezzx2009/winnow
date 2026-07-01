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


class Account(SQLModel, table=True):
    """一个被监控的邮箱账号。Phase 1 只有一行。"""

    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(index=True, unique=True)
    # INBOX 已处理到的最大 UID —— 重启后只拉取更大的 UID，避免重复处理旧邮件
    last_seen_uid: Optional[int] = Field(default=None)
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

    created_at: datetime = Field(default_factory=_utcnow)
