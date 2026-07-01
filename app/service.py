"""常驻服务：IMAP IDLE 长连接实时收信，断线自动重连。

收信触发（IDLE 唤醒 → 增量拉取）与处理逻辑（pipeline）解耦。
Phase 2 起：凭据与转发配置优先取自 DB（控制台可改），.env 作为回退；
阈值/目标邮箱/白黑名单每轮实时读取，改了立即生效（连接凭据/前缀需重连生效）。
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from sqlmodel import select

from datetime import datetime, timezone

from app.ai.minimax import MiniMaxAnalyzer
from app.config import Settings, settings
from app.db import get_or_create_primary_account, init_db, session_scope
from app.events import classify_connection_error, record_event
from app.mail.imap_client import ImapClient
from app.mail.smtp_forwarder import SmtpForwarder
from app.models import Account, SenderRule
from app.pipeline import process_message
from app.runtime import effective_credentials, runtime_config_for, sender_rules_from

logger = logging.getLogger(__name__)

_IDLE_TIMEOUT = 60
_RECONNECT_BASE_DELAY = 5
_RECONNECT_MAX_DELAY = 300


def build_imap(cfg: Settings, account: Account) -> ImapClient:
    email, auth_code = effective_credentials(account, cfg)
    return ImapClient(host=cfg.imap_host, port=cfg.imap_port, email=email, auth_code=auth_code)


def build_forwarder(cfg: Settings, account: Account) -> SmtpForwarder:
    email, auth_code = effective_credentials(account, cfg)
    rc = runtime_config_for(account, cfg)
    return SmtpForwarder(
        host=cfg.smtp_host,
        port=cfg.smtp_port,
        email=email,
        auth_code=auth_code,
        subject_prefix=rc.subject_prefix,
        min_interval_seconds=rc.forward_interval_seconds,
    )


def _update_last_seen(account_id: int, uid: int) -> None:
    with session_scope() as s:
        acc = s.get(Account, account_id)
        if acc is not None and (acc.last_seen_uid is None or uid > acc.last_seen_uid):
            acc.last_seen_uid = uid


def _get_last_seen(account_id: int) -> Optional[int]:
    with session_scope() as s:
        acc = s.get(Account, account_id)
        return acc.last_seen_uid if acc else None


def _touch_poll(account_id: int) -> None:
    """更新收信服务心跳，供控制台判断在线状态。"""
    with session_scope() as s:
        acc = s.get(Account, account_id)
        if acc is not None:
            acc.last_poll_at = datetime.now(timezone.utc)


class WinnowService:
    def __init__(self, cfg: Settings) -> None:
        self.cfg = cfg
        init_db()
        self.account = get_or_create_primary_account(cfg.email_126)
        self.analyzer = MiniMaxAnalyzer()
        self.imap = build_imap(cfg, self.account)
        self.forwarder = build_forwarder(cfg, self.account)

    def process_batch(
        self, account: Account, messages, *, dry_run: bool = False, advance_uid: bool = True
    ) -> None:
        """处理一批邮件。每次从 DB 重读账号配置与规则 —— 控制台改动即时生效。"""
        with session_scope() as s:
            fresh = s.get(Account, account.id) or account
            rules = sender_rules_from(
                s.exec(select(SenderRule).where(SenderRule.account_id == account.id)).all()
            )
            config = runtime_config_for(fresh, self.cfg)
        for msg in messages:
            with session_scope() as s:
                process_message(
                    s, account, msg,
                    analyzer=self.analyzer, forwarder=self.forwarder,
                    config=config, sender_rules=rules, dry_run=dry_run,
                )
            if msg.uid and advance_uid and not dry_run:
                _update_last_seen(account.id, int(msg.uid))

    def _process_new(self, account: Account) -> None:
        with session_scope() as s:
            fresh = s.get(Account, account.id) or account
            enabled = fresh.enabled
        if not enabled:
            logger.info("账号已在控制台停用，跳过本轮处理。")
            return
        messages = self.imap.fetch_since(_get_last_seen(account.id))
        self.process_batch(account, messages, advance_uid=True)

    def run(self) -> None:
        logger.info("Winnow 服务启动，监控 %s", self.account.email)
        reconnect_delay = _RECONNECT_BASE_DELAY
        had_error = False
        while True:
            try:
                self.imap.connect()
                reconnect_delay = _RECONNECT_BASE_DELAY
                _touch_poll(self.account.id)
                if had_error:
                    record_event("info", "connection", "IMAP 重连成功", self.account.id)
                    had_error = False

                if _get_last_seen(self.account.id) is None:
                    max_uid = self.imap.get_max_uid()
                    _update_last_seen(self.account.id, max_uid or 0)
                    logger.info("已设增量基线 last_seen_uid=%s（不回捞旧邮件）", max_uid or 0)

                self._process_new(self.account)  # 追平断线期间的邮件

                while True:
                    has_new = self.imap.idle_wait(timeout=_IDLE_TIMEOUT)
                    _touch_poll(self.account.id)  # 心跳
                    if has_new:
                        logger.info("IDLE 检测到新活动，拉取处理…")
                        self._process_new(self.account)
            except KeyboardInterrupt:
                logger.info("收到中断，退出。")
                self.imap.disconnect()
                return
            except Exception as exc:  # noqa: BLE001
                had_error = True
                kind = classify_connection_error(str(exc))
                hint = "（授权码可能失效，请到控制台重新绑定）" if kind == "auth" else ""
                record_event("error", kind, f"收信连接/处理异常：{exc}{hint}", self.account.id)
                logger.error("连接/处理异常：%s；%ds 后重连", exc, reconnect_delay)
                self.imap.disconnect()
                time.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, _RECONNECT_MAX_DELAY)


def run() -> None:
    WinnowService(settings).run()
