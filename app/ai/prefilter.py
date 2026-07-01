"""第一级过滤：规则预筛，省 MiniMax 额度、避开限流。

只在「非常有把握是营销/群发」时才直接判为不重要、跳过模型。
因为「漏判重要邮件」代价远大于「误转发广告」，所以预筛保持保守：
拿不准的一律交给模型（返回 None）。

明确的营销信号（任一即拦下）：
  - List-Unsubscribe / List-Id 头（群发邮件的强特征，含退订链接）
  - Precedence: bulk/list/junk
  - Auto-Submitted: auto-generated（自动群发）
  - 主题命中营销关键词
注意：仅凭 noreply@ 之类发件人不足以拦下（登录提醒等重要通知也用 noreply@），
故这类只作为交给模型的信号，不在此直接判定。
"""

from email.message import Message
from typing import Optional

from app.ai.base import Analysis

# 主题里的营销/促销关键词（命中即视为营销）
_MARKETING_SUBJECT_KEYWORDS = (
    "退订", "优惠", "促销", "大促", "折扣", "秒杀", "满减", "限时", "特惠", "钜惠",
    "清仓", "抢购", "领取", "红包", "礼包",
    "unsubscribe", "newsletter", "sale", "% off", "deal", "promo", "coupon",
    "discount", "clearance", "flash sale", "limited time",
)

_BULK_PRECEDENCE = {"bulk", "list", "junk"}


def _header(msg: Message, name: str) -> str:
    value = msg.get(name)
    return value.strip() if value else ""


def run_prefilter(msg: Message, subject: str) -> Optional[Analysis]:
    """返回 Analysis 表示「预筛判定为不重要」；返回 None 表示「交给模型判断」。"""

    # 1) 群发/订阅类邮件头
    if _header(msg, "List-Unsubscribe") or _header(msg, "List-Id"):
        return Analysis(
            is_important=False,
            confidence=0.9,
            reason="规则预筛：含 List-Unsubscribe/List-Id 群发退订头",
            category="营销",
            prefiltered=True,
        )

    precedence = _header(msg, "Precedence").lower()
    if precedence in _BULK_PRECEDENCE:
        return Analysis(
            is_important=False,
            confidence=0.85,
            reason=f"规则预筛：Precedence: {precedence}（群发）",
            category="营销",
            prefiltered=True,
        )

    if _header(msg, "Auto-Submitted").lower().startswith("auto-generated"):
        # 自动群发；但保守起见仅当同时命中主题关键词才拦（避免拦掉自动发的账单/验证码）
        if _subject_is_marketing(subject):
            return Analysis(
                is_important=False,
                confidence=0.8,
                reason="规则预筛：自动群发 + 营销主题",
                category="营销",
                prefiltered=True,
            )

    # 2) 主题营销关键词
    if _subject_is_marketing(subject):
        return Analysis(
            is_important=False,
            confidence=0.8,
            reason="规则预筛：主题命中营销关键词",
            category="营销",
            prefiltered=True,
        )

    # 拿不准 —— 交给模型
    return None


def _subject_is_marketing(subject: str) -> bool:
    low = (subject or "").lower()
    return any(kw in low for kw in _MARKETING_SUBJECT_KEYWORDS)
