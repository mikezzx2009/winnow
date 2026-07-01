"""SMTP 转发器：以原 126 身份转发，完整保留原始邮件内容与附件。

转发策略（比「原邮件作附件」体验更原生、可靠性相当）：
  改写信封头 + 原样重发原始 MIME。
  - From 改为 126 地址（必须，否则 smtp.126.com 拒发；且这样 SPF/DKIM 才对齐）；
    显示名保留原始发件人，形如 "张三 (via Winnow) <xxx@126.com>"。
  - Reply-To 设为原始发件人（回复能回到真人）。
  - To 设为目标邮箱，Subject 加可配置前缀。
  - 删除原 DKIM-Signature/Return-Path 等（改了头后原签名已失效，由 126 重新签名）。
  - 原始正文、内联图片、附件全部原样保留（深拷贝原 MIME）。

反垃圾：相邻两封转发之间强制最小间隔（每日上限由上层 pipeline 按 DB 计数控制）。
"""

from __future__ import annotations

import copy
import logging
import smtplib
import ssl
import threading
import time
from email.message import Message
from email.utils import formataddr, make_msgid, parseaddr

logger = logging.getLogger(__name__)

# 转发时需要删除/覆盖的原始头（避免与新信封冲突或携带失效签名）
_HEADERS_TO_STRIP = (
    "From", "To", "Cc", "Bcc", "Reply-To", "Subject", "Message-ID", "Return-Path",
    "Delivered-To", "Sender", "DKIM-Signature", "X-Google-DKIM-Signature",
    "Authentication-Results", "ARC-Seal", "ARC-Message-Signature",
    "ARC-Authentication-Results",
)


def build_forward_message(
    original: Message, *, from_addr: str, to_addr: str, subject_prefix: str
) -> Message:
    """基于原始邮件构造转发邮件（纯函数，便于测试；不发送）。"""
    fwd = copy.deepcopy(original)

    orig_from = original.get("From", "")
    orig_name, orig_email = parseaddr(orig_from)
    orig_subject = original.get("Subject", "") or "(无主题)"

    for header in _HEADERS_TO_STRIP:
        while header in fwd:
            del fwd[header]

    display = orig_name or orig_email or "Winnow"
    fwd["From"] = formataddr((f"{display} (via Winnow)", from_addr))
    fwd["To"] = to_addr
    if orig_from:
        fwd["Reply-To"] = orig_from
    fwd["Subject"] = f"{subject_prefix}{orig_subject}"
    fwd["Message-ID"] = make_msgid(domain=from_addr.split("@")[-1])
    # 留档：原始发件人与原始 Message-ID
    fwd["X-Original-From"] = orig_from
    if original.get("Message-ID"):
        fwd["X-Original-Message-ID"] = original.get("Message-ID")
    fwd["X-Winnow-Forwarded"] = "yes"
    return fwd


class SmtpForwarder:
    """通过 smtp.126.com 发送转发邮件，内置最小发送间隔。"""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        email: str,
        auth_code: str,
        subject_prefix: str,
        min_interval_seconds: int,
    ) -> None:
        self.host = host
        self.port = port
        self.email = email
        self.auth_code = auth_code
        self.subject_prefix = subject_prefix
        self.min_interval_seconds = min_interval_seconds
        self._lock = threading.Lock()
        self._last_send_ts = 0.0

    def _respect_interval(self) -> None:
        with self._lock:
            elapsed = time.monotonic() - self._last_send_ts
            wait = self.min_interval_seconds - elapsed
            if wait > 0:
                logger.info("转发限速：等待 %.1fs", wait)
                time.sleep(wait)
            self._last_send_ts = time.monotonic()

    def forward(self, original: Message, target: str) -> str:
        """转发一封邮件到 target，返回新邮件的 Message-ID。异常向上抛。"""
        fwd = build_forward_message(
            original,
            from_addr=self.email,
            to_addr=target,
            subject_prefix=self.subject_prefix,
        )
        self._respect_interval()
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(self.host, self.port, context=context, timeout=30) as server:
            server.login(self.email, self.auth_code)
            server.send_message(fwd, from_addr=self.email, to_addrs=[target])
        logger.info("已转发至 %s（原主题已加前缀）", target)
        return fwd["Message-ID"]
