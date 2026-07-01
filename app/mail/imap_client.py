"""126 IMAP 客户端封装。

要点（已由 scripts/check_imap.py 验证）：
  - 登录后立刻发 IMAP ID 命令，规避网易 "Unsafe Login"。
  - 只处理「服务启动后新到」的邮件：以 UID 增量拉取（UID > last_seen）。
  - 支持 IMAP IDLE 长连接实时收信；断线由上层 service 负责重连。
"""

from __future__ import annotations

import imaplib
import logging
from typing import List, Optional

from imap_tools import AND, MailBox
from imap_tools.message import MailMessage

logger = logging.getLogger(__name__)


def _send_imap_id(client: imaplib.IMAP4, contact: str) -> None:
    """发送 IMAP ID 命令声明客户端身份（RFC 2971），规避网易 "Unsafe Login"。"""
    imaplib.Commands["ID"] = ("AUTH", "SELECTED", "NONAUTH")
    fields = {
        "name": "Winnow",
        "version": "1.0.0",
        "vendor": "Winnow Mail Forwarder",
        "contact": contact,
    }
    tokens: List[str] = []
    for key, value in fields.items():
        tokens.append(f'"{key}"')
        tokens.append(f'"{value}"')
    arg = "(" + " ".join(tokens) + ")"
    client._simple_command("ID", arg)  # type: ignore[attr-defined]


class ImapClient:
    """对 imap-tools MailBox 的薄封装，处理 126 的连接特殊性。"""

    def __init__(self, host: str, port: int, email: str, auth_code: str, folder: str = "INBOX") -> None:
        self.host = host
        self.port = port
        self.email = email
        self.auth_code = auth_code
        self.folder = folder
        self.mailbox: Optional[MailBox] = None

    def connect(self) -> None:
        """建立连接：登录 → 发 ID → 选择文件夹。"""
        mailbox = MailBox(self.host, port=self.port)
        # initial_folder=None：先登录、不选文件夹，好在 SELECT 前插入 ID 命令
        mailbox.login(self.email, self.auth_code, initial_folder=None)
        _send_imap_id(mailbox.client, self.email)
        mailbox.folder.set(self.folder)
        self.mailbox = mailbox
        logger.info("IMAP 已连接 %s:%s，文件夹=%s", self.host, self.port, self.folder)

    def disconnect(self) -> None:
        if self.mailbox is not None:
            try:
                self.mailbox.logout()
            except Exception:  # noqa: BLE001
                pass
            self.mailbox = None

    def get_max_uid(self) -> Optional[int]:
        """返回当前文件夹最大 UID（无邮件时返回 None）。用于设置增量基线。"""
        assert self.mailbox is not None
        uids = self.mailbox.uids()
        return max((int(u) for u in uids), default=None)

    def fetch_since(self, last_seen_uid: Optional[int]) -> List[MailMessage]:
        """拉取 UID 严格大于 last_seen_uid 的邮件（完整邮件，用于转发）。

        IMAP 的 "N:*" 语义会把最大 UID 也带上，故这里再按 int 过滤一遍。
        """
        assert self.mailbox is not None
        start = (last_seen_uid or 0) + 1
        messages: List[MailMessage] = []
        for msg in self.mailbox.fetch(
            AND(uid=f"{start}:*"), mark_seen=False, bulk=True
        ):
            if msg.uid and int(msg.uid) > (last_seen_uid or 0):
                messages.append(msg)
        messages.sort(key=lambda m: int(m.uid))
        return messages

    def fetch_last(self, n: int) -> List[MailMessage]:
        """拉取最近 n 封（完整邮件）。仅用于 CLI 回捞/演练，正常收信不用。"""
        assert self.mailbox is not None
        messages = list(
            self.mailbox.fetch(reverse=True, limit=n, mark_seen=False, bulk=True)
        )
        messages.sort(key=lambda m: int(m.uid))
        return messages

    def idle_wait(self, timeout: int = 60) -> bool:
        """IMAP IDLE 等待新邮件事件。返回 True 表示期间有新活动。"""
        assert self.mailbox is not None
        with self.mailbox.idle as idle:
            responses = idle.poll(timeout=timeout)
        return bool(responses)
