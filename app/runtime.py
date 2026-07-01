"""运行期配置桥接：把「DB 中账号级配置」与「.env 默认值」合并成管线用的 RuntimeConfig。

这样控制台改了阈值/目标邮箱/白黑名单，常驻服务下一轮即生效，且 Phase 1 的 .env 仍作为回退。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from app.config import Settings
from app.crypto import decrypt
from app.models import Account, SenderRule


@dataclass
class SenderRules:
    whitelist: List[str] = field(default_factory=list)   # 命中即必转发
    blacklist: List[str] = field(default_factory=list)   # 命中即必拦截

    def match_whitelist(self, from_addr: str) -> bool:
        low = (from_addr or "").lower()
        return any(p in low for p in self.whitelist)

    def match_blacklist(self, from_addr: str) -> bool:
        low = (from_addr or "").lower()
        return any(p in low for p in self.blacklist)


@dataclass
class RuntimeConfig:
    """管线/转发器读取的有效配置（字段名与 Settings 对齐，便于复用）。"""

    forward_to: str
    subject_prefix: str
    importance_threshold: float
    forward_interval_seconds: int
    daily_forward_limit: int


def runtime_config_for(account: Account, settings: Settings) -> RuntimeConfig:
    """账号级配置优先，缺省回退到 .env。"""
    return RuntimeConfig(
        forward_to=account.forward_to or settings.forward_to,
        subject_prefix=account.subject_prefix or settings.subject_prefix,
        importance_threshold=(
            account.importance_threshold
            if account.importance_threshold is not None
            else settings.importance_threshold
        ),
        forward_interval_seconds=account.forward_interval_seconds or settings.forward_interval_seconds,
        daily_forward_limit=account.daily_forward_limit or settings.daily_forward_limit,
    )


def effective_credentials(account: Account, settings: Settings) -> tuple[str, str]:
    """返回 (email, auth_code)：优先用 DB 中绑定的（解密），否则回退 .env。"""
    email = account.email or settings.email_126
    if account.imap_auth_code_encrypted:
        auth_code = decrypt(account.imap_auth_code_encrypted)
    else:
        auth_code = settings.imap_auth_code
    return email, auth_code


def sender_rules_from(rules: List[SenderRule]) -> SenderRules:
    return SenderRules(
        whitelist=[r.pattern.lower() for r in rules if r.kind == "whitelist"],
        blacklist=[r.pattern.lower() for r in rules if r.kind == "blacklist"],
    )
