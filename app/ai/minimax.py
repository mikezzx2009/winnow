"""第二级判断：MiniMax 适配器（可替换）。

- base_url / api_key / model 全部从配置读取。
- 让模型返回结构化 JSON；对「夹带多余文字 / 代码围栏」做健壮解析。
- 被限流时（HTTP 429 或 MiniMax base_resp 1002/1039）自动重试 + 指数退避。
- 任何异常兜底：返回「保守转发」的结果（漏判代价更大，宁可错发）。
"""

from __future__ import annotations

import json
import logging
import random
import re
import time

import httpx

from app.ai.base import Analysis
from app.config import settings

logger = logging.getLogger(__name__)

# MiniMax 触发限流的业务码
_RATE_LIMIT_CODES = {1002, 1039}
_MAX_BODY_CHARS = 4000  # 发给模型的正文上限（省 token + 隐私）

_SYSTEM_PROMPT = (
    "你是邮件重要性分类助手。判断一封邮件对收件人本人是否「重要」——"
    "即非广告、非垃圾、非营销通知。工作、账单、账号安全、真人往来、预约、"
    "重要通知视为重要；促销、广告、群发营销视为不重要。\n"
    "只输出一个 JSON 对象，不要任何多余文字或解释，格式：\n"
    '{"is_important": true/false, "confidence": 0到1的小数, '
    '"reason": "简短中文理由", "category": "工作/账单/社交/营销/垃圾/其它 之一"}'
)


def extract_json(text: str) -> dict:
    """从可能夹带多余文字/代码围栏的模型输出中抠出第一个 JSON 对象。"""
    if not text:
        raise ValueError("空响应")
    cleaned = text.strip()
    # 去掉 ```json ... ``` 或 ``` ... ``` 围栏
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1).strip()
    # 直接尝试
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    # 退而求其次：抓取第一个 {...} 平衡片段
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        raise ValueError(f"未找到 JSON：{cleaned[:200]}")
    return json.loads(match.group(0))


def _to_analysis(data: dict) -> Analysis:
    """把解析出的 dict 规整为 Analysis，字段缺失/类型异常都给安全默认值。"""
    is_important = bool(data.get("is_important", True))  # 缺失时倾向重要
    try:
        confidence = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = min(max(confidence, 0.0), 1.0)
    reason = str(data.get("reason", "")).strip()[:300]
    category = str(data.get("category", "其它")).strip()[:20] or "其它"
    return Analysis(
        is_important=is_important,
        confidence=confidence,
        reason=reason,
        category=category,
        prefiltered=False,
    )


class MiniMaxAnalyzer:
    """MiniMax chatcompletion_v2 适配器。"""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        max_retries: int = 5,
        timeout: float = 60.0,
    ) -> None:
        self.base_url = (base_url or settings.minimax_base_url).rstrip("/")
        self.api_key = api_key or settings.minimax_api_key
        self.model = model or settings.minimax_model
        self.max_retries = max_retries
        self.timeout = timeout
        if not self.api_key:
            raise ValueError("MINIMAX_API_KEY 未配置")

    @property
    def _url(self) -> str:
        return f"{self.base_url}/text/chatcompletion_v2"

    def analyze(self, *, subject: str, from_addr: str, body: str) -> Analysis:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"发件人：{from_addr}\n"
                        f"主题：{subject}\n"
                        f"正文（可能被截断）：\n{body[:_MAX_BODY_CHARS]}"
                    ),
                },
            ],
            "temperature": 0.1,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            content = self._post_with_retry(payload, headers)
            return _to_analysis(extract_json(content))
        except Exception as exc:  # noqa: BLE001
            # 兜底：判断失败时倾向转发，绝不因 AI 故障丢掉可能重要的邮件
            logger.warning("MiniMax 分析失败，回退为保守转发：%s", exc)
            return Analysis(
                is_important=True,
                confidence=0.0,
                reason=f"AI 判断失败，保守转发（{type(exc).__name__}）",
                category="其它",
                prefiltered=False,
            )

    def _post_with_retry(self, payload: dict, headers: dict) -> str:
        """发起请求，处理限流重试（指数退避 + 抖动）。返回模型文本内容。"""
        last_error = "未知错误"
        with httpx.Client(timeout=self.timeout) as client:
            for attempt in range(self.max_retries):
                rate_limited = False
                try:
                    resp = client.post(self._url, headers=headers, json=payload)
                except httpx.HTTPError as exc:
                    last_error = f"网络异常 {type(exc).__name__}: {exc}"
                    rate_limited = False
                else:
                    if resp.status_code == 429:
                        last_error = "HTTP 429 限流"
                        rate_limited = True
                    elif resp.status_code != 200:
                        last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                    else:
                        data = resp.json()
                        code = (data.get("base_resp") or {}).get("status_code", 0)
                        if code in _RATE_LIMIT_CODES:
                            last_error = f"MiniMax 限流 base_resp={code}"
                            rate_limited = True
                        elif code not in (0, None):
                            # 其它业务错误（鉴权/参数等），重试无益，直接抛出
                            msg = (data.get("base_resp") or {}).get("status_msg", "")
                            raise RuntimeError(f"MiniMax 业务错误 {code}: {msg}")
                        else:
                            choices = data.get("choices") or []
                            if not choices:
                                raise RuntimeError("MiniMax 响应无 choices")
                            return choices[0].get("message", {}).get("content", "")

                # 需要重试：指数退避 + 抖动
                if attempt < self.max_retries - 1:
                    delay = min(2 ** attempt, 30) + random.uniform(0, 1)
                    logger.info(
                        "MiniMax 第 %d 次重试（%s），%.1fs 后重试", attempt + 1, last_error, delay
                    )
                    time.sleep(delay)

        raise RuntimeError(f"MiniMax 重试 {self.max_retries} 次仍失败：{last_error}")
