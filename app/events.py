"""Phase 3：系统事件/告警记录 + 服务健康判断。

record_event 把值得关注的事件写入 DB（并打日志），控制台据此展示告警。
故意做成「尽力而为」：记录失败绝不影响主流程。
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("winnow.events")

# 收信服务心跳超过该秒数未更新，则视为「可能离线」（约 3 个 IDLE 周期）
HEARTBEAT_STALE_SECONDS = 180


def record_event(level: str, kind: str, message: str, account_id: Optional[int] = None) -> None:
    """记录一条事件（level: info|warning|error, kind: connection|auth|forward|ratelimit|other）。"""
    # 延迟导入，避免与 db/models 形成导入环
    try:
        from app.db import session_scope
        from app.models import Event

        with session_scope() as session:
            session.add(
                Event(level=level, kind=kind, message=(message or "")[:500], account_id=account_id)
            )
    except Exception as exc:  # noqa: BLE001
        logger.error("record_event 写库失败：%s", exc)

    log = logger.error if level == "error" else logger.warning if level == "warning" else logger.info
    log("[%s/%s] %s", level, kind, message)


def classify_connection_error(message: str) -> str:
    """把 IMAP 连接异常粗分类为 auth（授权码失效）或 connection（网络/断开）。"""
    low = (message or "").lower()
    if any(k in low for k in ("login", "auth", "unsafe", "credential", "password")):
        return "auth"
    return "connection"


def is_healthy(seconds_since_poll: Optional[float], unresolved_errors: int) -> bool:
    """纯函数：心跳新鲜且无未处理错误 => 健康。便于单测。"""
    if seconds_since_poll is None:
        return False
    return seconds_since_poll <= HEARTBEAT_STALE_SECONDS and unresolved_errors == 0
