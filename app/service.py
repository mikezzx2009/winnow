"""收信常驻服务（多账号）。

Supervisor 周期性对账「已启用且有凭据的账号」与「运行中的 worker 线程」：
为新账号启动 AccountWorker（各自独立 IMAP IDLE 长连接 + 断线重连），为停用/删除的账号停线程。
单账号时行为与之前一致（正好一个 worker）。

收信触发（IDLE 唤醒 → 增量拉取）与处理逻辑（pipeline）解耦；每轮从 DB 实时读配置与名单。
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from sqlmodel import select

from app.ai.minimax import MiniMaxAnalyzer
from app.config import Settings, settings
from app.db import get_or_create_primary_account, init_db, session_scope
from app.events import classify_connection_error, record_event
from app.mail.imap_client import ImapClient
from app.mail.smtp_forwarder import SmtpForwarder
from app.models import Account, SenderRule
from app.pipeline import process_message
from app.runtime import (
    account_has_credentials,
    effective_credentials,
    runtime_config_for,
    sender_rules_from,
)

logger = logging.getLogger(__name__)

_IDLE_TIMEOUT = 60
_RECONNECT_BASE_DELAY = 5
_RECONNECT_MAX_DELAY = 300
_RECONCILE_INTERVAL = 60  # supervisor 每隔多少秒对账一次账号列表


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


class AccountWorker:
    """负责单个账号的收信处理。既用于常驻 worker 线程，也用于 CLI 的 once/backfill。"""

    def __init__(self, cfg: Settings, account: Account) -> None:
        self.cfg = cfg
        self.account = account
        _, auth_code = effective_credentials(account, cfg)
        self.auth_code = auth_code
        self.analyzer = MiniMaxAnalyzer()
        self.imap = ImapClient(
            host=cfg.imap_host, port=cfg.imap_port, email=account.email, auth_code=auth_code or ""
        )
        rc = runtime_config_for(account, cfg)
        self.forwarder = SmtpForwarder(
            host=cfg.smtp_host,
            port=cfg.smtp_port,
            email=account.email,
            auth_code=auth_code or "",
            subject_prefix=rc.subject_prefix,
            min_interval_seconds=rc.forward_interval_seconds,
        )

    def process_batch(self, messages, *, dry_run: bool = False, advance_uid: bool = True) -> None:
        """处理一批邮件，每次从 DB 重读该账号的配置与名单（控制台改动即时生效）。"""
        with session_scope() as s:
            fresh = s.get(Account, self.account.id) or self.account
            rules = sender_rules_from(
                s.exec(select(SenderRule).where(SenderRule.account_id == self.account.id)).all()
            )
            config = runtime_config_for(fresh, self.cfg)
        for msg in messages:
            with session_scope() as s:
                process_message(
                    s, self.account, msg,
                    analyzer=self.analyzer, forwarder=self.forwarder,
                    config=config, sender_rules=rules, dry_run=dry_run,
                )
            if msg.uid and advance_uid and not dry_run:
                _update_last_seen(self.account.id, int(msg.uid))

    def _process_new(self) -> None:
        with session_scope() as s:
            fresh = s.get(Account, self.account.id)
            enabled = fresh.enabled if fresh else False
        if not enabled:
            return
        messages = self.imap.fetch_since(_get_last_seen(self.account.id))
        self.process_batch(messages, advance_uid=True)

    def run(self, stop_event: threading.Event) -> None:
        """常驻循环：连接 → IDLE 收信 → 断线重连，直到 stop_event 置位。"""
        logger.info("worker[%s] 启动，监控 %s", self.account.id, self.account.email)
        reconnect_delay = _RECONNECT_BASE_DELAY
        had_error = False
        while not stop_event.is_set():
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
                    logger.info("worker[%s] 已设基线 last_seen_uid=%s", self.account.id, max_uid or 0)

                self._process_new()
                while not stop_event.is_set():
                    has_new = self.imap.idle_wait(timeout=_IDLE_TIMEOUT)
                    _touch_poll(self.account.id)
                    if has_new:
                        self._process_new()
            except Exception as exc:  # noqa: BLE001
                had_error = True
                kind = classify_connection_error(str(exc))
                hint = "（授权码可能失效，请到控制台重新绑定）" if kind == "auth" else ""
                record_event("error", kind, f"worker[{self.account.id}] 异常：{exc}{hint}", self.account.id)
                logger.error("worker[%s] 异常：%s；%ds 后重连", self.account.id, exc, reconnect_delay)
                self.imap.disconnect()
                stop_event.wait(reconnect_delay)  # 可被停止打断的退避
                reconnect_delay = min(reconnect_delay * 2, _RECONNECT_MAX_DELAY)
        self.imap.disconnect()
        logger.info("worker[%s] 已停止", self.account.id)


def startable_accounts(cfg: Settings) -> List[Account]:
    """已启用且具备凭据（已绑定或就是 .env 账号）的账号。"""
    with session_scope() as s:
        accounts = s.exec(select(Account).where(Account.enabled == True)).all()  # noqa: E712
        for a in accounts:
            s.expunge(a)
    return [a for a in accounts if account_has_credentials(a, cfg)]


class Supervisor:
    """多账号监督者：按账号列表启停 worker 线程。"""

    def __init__(self, cfg: Settings) -> None:
        self.cfg = cfg
        self.workers: Dict[int, Tuple[threading.Thread, threading.Event]] = {}

    def _reconcile(self) -> None:
        desired = {a.id: a for a in startable_accounts(self.cfg)}
        # 停掉不再需要的（停用/删除/凭据被清）
        for account_id in list(self.workers):
            if account_id not in desired:
                logger.info("停止账号 %s 的 worker", account_id)
                self.workers[account_id][1].set()
                del self.workers[account_id]
        # 启动新增的
        for account_id, account in desired.items():
            if account_id not in self.workers:
                stop = threading.Event()
                worker = AccountWorker(self.cfg, account)
                thread = threading.Thread(
                    target=worker.run, args=(stop,), daemon=True, name=f"winnow-acc-{account_id}"
                )
                thread.start()
                self.workers[account_id] = (thread, stop)
                logger.info("已启动账号 %s(%s) 的 worker", account_id, account.email)

    def run(self) -> None:
        init_db()
        get_or_create_primary_account(self.cfg.email_126)
        logger.info("Winnow 收信服务（多账号）启动")
        try:
            while True:
                self._reconcile()
                if not self.workers:
                    logger.info("暂无可启动账号（需 enabled 且已绑定授权码）。等待…")
                time.sleep(_RECONCILE_INTERVAL)
        except KeyboardInterrupt:
            logger.info("收到中断，停止所有 worker…")
            for _, stop in self.workers.values():
                stop.set()


def run() -> None:
    Supervisor(settings).run()
