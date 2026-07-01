"""常驻服务：IMAP IDLE 长连接实时收信，断线自动重连。

收信触发（IDLE 唤醒 → 增量拉取）与处理逻辑（pipeline）解耦：本模块只负责
「发现新邮件并交给 pipeline」，不含判断/转发细节。
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from sqlmodel import select

from app.ai.minimax import MiniMaxAnalyzer
from app.config import Settings, settings
from app.db import ensure_account, init_db, session_scope
from app.mail.imap_client import ImapClient
from app.mail.smtp_forwarder import SmtpForwarder
from app.models import Account
from app.pipeline import process_message

logger = logging.getLogger(__name__)

_IDLE_TIMEOUT = 60           # 每次 IDLE 等待秒数（到点即返回，兼作心跳）
_RECONNECT_BASE_DELAY = 5    # 断线重连基础退避秒数
_RECONNECT_MAX_DELAY = 300


def build_components(cfg: Settings) -> tuple[ImapClient, MiniMaxAnalyzer, SmtpForwarder]:
    """按配置装配三大组件。"""
    imap = ImapClient(
        host=cfg.imap_host,
        port=cfg.imap_port,
        email=cfg.email_126,
        auth_code=cfg.imap_auth_code,
    )
    analyzer = MiniMaxAnalyzer()
    forwarder = SmtpForwarder(
        host=cfg.smtp_host,
        port=cfg.smtp_port,
        email=cfg.email_126,
        auth_code=cfg.imap_auth_code,
        subject_prefix=cfg.subject_prefix,
        min_interval_seconds=cfg.forward_interval_seconds,
    )
    return imap, analyzer, forwarder


def _update_last_seen(account_id: int, uid: int) -> None:
    with session_scope() as s:
        acc = s.get(Account, account_id)
        if acc is not None and (acc.last_seen_uid is None or uid > acc.last_seen_uid):
            acc.last_seen_uid = uid


def _get_last_seen(account_id: int) -> Optional[int]:
    with session_scope() as s:
        acc = s.get(Account, account_id)
        return acc.last_seen_uid if acc else None


class WinnowService:
    def __init__(self, cfg: Settings) -> None:
        self.cfg = cfg
        self.imap, self.analyzer, self.forwarder = build_components(cfg)

    def _process_new(self, account: Account) -> None:
        last_seen = _get_last_seen(account.id)
        messages = self.imap.fetch_since(last_seen)
        for msg in messages:
            with session_scope() as s:
                process_message(
                    s, account, msg,
                    analyzer=self.analyzer,
                    forwarder=self.forwarder,
                    settings=self.cfg,
                )
            if msg.uid:
                _update_last_seen(account.id, int(msg.uid))

    def run(self) -> None:
        init_db()
        account = ensure_account(self.cfg.email_126)
        logger.info("Winnow 服务启动，监控 %s", account.email)

        reconnect_delay = _RECONNECT_BASE_DELAY
        while True:
            try:
                self.imap.connect()
                reconnect_delay = _RECONNECT_BASE_DELAY  # 连接成功，重置退避

                # 首次启动设基线：只处理「启动后新到」的邮件，不回捞旧邮件
                if _get_last_seen(account.id) is None:
                    max_uid = self.imap.get_max_uid()
                    _update_last_seen(account.id, max_uid or 0)
                    logger.info("已设增量基线 last_seen_uid=%s（不回捞旧邮件）", max_uid or 0)

                # 连接后先追平一次（覆盖断线期间到达的邮件）
                self._process_new(account)

                # 进入 IDLE 循环
                while True:
                    has_new = self.imap.idle_wait(timeout=_IDLE_TIMEOUT)
                    if has_new:
                        logger.info("IDLE 检测到新活动，拉取处理…")
                        self._process_new(account)
            except KeyboardInterrupt:
                logger.info("收到中断，退出。")
                self.imap.disconnect()
                return
            except Exception as exc:  # noqa: BLE001
                logger.error("连接/处理异常：%s；%ds 后重连", exc, reconnect_delay)
                self.imap.disconnect()
                time.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, _RECONNECT_MAX_DELAY)


def run() -> None:
    WinnowService(settings).run()
