"""处理管线：收信触发 → 去重 → 预筛 → AI → 决策 → 转发 → 落库。

与「收信触发」解耦：本模块只处理「一封已取回的邮件」，不关心它从 IDLE 还是 CLI 来。
"""

from __future__ import annotations

import html
import logging
import re
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func
from sqlmodel import Session, select

from app.ai.base import Analysis, Analyzer
from app.ai.prefilter import run_prefilter
from app.mail.smtp_forwarder import SmtpForwarder
from app.models import Account, ProcessedEmail
from app.runtime import RuntimeConfig, SenderRules

logger = logging.getLogger(__name__)

_SUMMARY_MAX = 120  # 短摘要长度（数据最小化，不存完整正文）


def should_forward(analysis: Analysis, threshold: float) -> bool:
    """决策：重要则转发；「不重要但置信度低于阈值」也转发（漏判代价更大）。"""
    if analysis.is_important:
        return True
    return analysis.confidence < threshold


def _strip_html(raw: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", raw)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def extract_body(msg) -> str:
    text = (msg.text or "").strip()
    if not text and msg.html:
        text = _strip_html(msg.html)
    return text


def _message_id_of(msg, account_id: int) -> str:
    mid = (msg.obj.get("Message-ID") or "").strip()
    if mid:
        return mid
    # 极少数邮件无 Message-ID：用 account+uid 合成一个稳定的去重键
    return f"<no-mid-{account_id}-{msg.uid}@winnow.local>"


def _daily_forward_count(session: Session, account_id: int) -> int:
    start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    stmt = (
        select(func.count())
        .select_from(ProcessedEmail)
        .where(
            ProcessedEmail.account_id == account_id,
            ProcessedEmail.forwarded == True,  # noqa: E712
            ProcessedEmail.forwarded_at >= start,
        )
    )
    return session.exec(stmt).one()


def process_message(
    session: Session,
    account: Account,
    msg,
    *,
    analyzer: Analyzer,
    forwarder: SmtpForwarder,
    config: RuntimeConfig,
    sender_rules: SenderRules | None = None,
    dry_run: bool = False,
) -> ProcessedEmail:
    """处理单封邮件并落库；幂等（已处理过的直接跳过，绝不重复转发）。"""
    account_id = account.id
    message_id = _message_id_of(msg, account_id)

    # --- 幂等去重 ---
    existing = session.exec(
        select(ProcessedEmail).where(
            ProcessedEmail.account_id == account_id,
            ProcessedEmail.message_id == message_id,
        )
    ).first()
    if existing is not None:
        logger.info("跳过已处理邮件 UID=%s（Message-ID 已存在）", msg.uid)
        return existing

    subject = msg.subject or ""
    from_addr = msg.from_ or ""
    received_at = msg.date if isinstance(msg.date, datetime) else None

    record = ProcessedEmail(
        account_id=account_id,
        message_id=message_id,
        uid=str(msg.uid) if msg.uid else None,
        from_addr=from_addr[:320],
        subject=subject[:500],
        received_at=received_at,
    )

    rules = sender_rules or SenderRules()

    # --- 第零级：发件人白/黑名单（优先级最高，直接定性、不调模型）---
    if rules.match_blacklist(from_addr):
        analysis: Optional[Analysis] = Analysis(
            is_important=False, confidence=1.0, reason="发件人在黑名单", category="黑名单",
            prefiltered=True,
        )
        record.short_summary = analysis.reason[:_SUMMARY_MAX]
    elif rules.match_whitelist(from_addr):
        analysis = Analysis(
            is_important=True, confidence=1.0, reason="发件人在白名单", category="白名单",
            prefiltered=True,
        )
        record.short_summary = analysis.reason[:_SUMMARY_MAX]
    else:
        # --- 第一级：规则预筛 ---
        analysis = run_prefilter(msg.obj, subject)
        # --- 第二级：模型判断（仅在预筛拿不准时）---
        if analysis is None:
            body = extract_body(msg)
            analysis = analyzer.analyze(subject=subject, from_addr=from_addr, body=body)
            record.short_summary = body[:_SUMMARY_MAX]
        else:
            record.short_summary = analysis.reason[:_SUMMARY_MAX]

    record.prefiltered = analysis.prefiltered
    record.is_important = analysis.is_important
    record.confidence = analysis.confidence
    record.reason = analysis.reason
    record.category = analysis.category

    # --- 决策 + 转发 ---
    want_forward = should_forward(analysis, config.importance_threshold)
    if want_forward and not dry_run:
        if _daily_forward_count(session, account_id) >= config.daily_forward_limit:
            record.error = "已达每日转发上限，排队至次日"
            logger.warning("每日转发上限已满，邮件 UID=%s 排队", msg.uid)
        else:
            try:
                forwarder.forward(msg.obj, config.forward_to)
                record.forwarded = True
                record.forwarded_at = datetime.now(timezone.utc)
            except Exception as exc:  # noqa: BLE001
                record.error = f"转发失败：{type(exc).__name__}: {exc}"[:500]
                logger.error("转发失败 UID=%s：%s", msg.uid, exc)
    elif want_forward and dry_run:
        record.error = "dry-run：本应转发但未实际发送"

    session.add(record)
    session.flush()

    logger.info(
        "已处理 UID=%s | 重要=%s 置信=%.2f 预筛=%s 转发=%s | %s | %s",
        msg.uid, record.is_important, record.confidence, record.prefiltered,
        record.forwarded, record.category, subject[:40],
    )
    return record
