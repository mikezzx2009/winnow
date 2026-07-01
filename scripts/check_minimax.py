"""命脉脚本 (c): 验证 MiniMax 订阅 Key 可用于程序化调用。

用订阅 Key 调一次 chatcompletion_v2，模拟真实用途（让模型对一封邮件做重要性分类）。
这一步能提前暴露 Token Plan 的权限/限流问题：
  - HTTP 状态码
  - MiniMax 业务码 base_resp.status_code (0=成功；非0 见下方 HINTS 参考)
  - 限流相关响应头 (若有)
  - 模型实际返回内容

运行：
    uv run python scripts/check_minimax.py

预期 PASS：HTTP 200 且 base_resp.status_code == 0，并能看到模型返回的分类结果。
"""

import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import require, settings  # noqa: E402

# MiniMax 业务码常见含义参考（用于快速定位问题，具体以官方文档为准）
HINTS = {
    1002: "触发限流 (RPM/TPM)，稍后重试；若频繁出现考虑改用按量付费 Key",
    1004: "鉴权失败：检查 MINIMAX_API_KEY 是否为订阅 Key(sk-sp-...)、BASE_URL 是否正确",
    1008: "余额不足 / 订阅额度耗尽",
    1013: "服务内部错误",
    1027: "输出命中安全策略",
    1039: "触发 TPM 限流",
    2013: "输入参数不合法（如 MINIMAX_MODEL 模型名不对/无权限）",
}


def main() -> int:
    api_key = require(settings.minimax_api_key, "MINIMAX_API_KEY")
    url = settings.minimax_base_url.rstrip("/") + "/text/chatcompletion_v2"

    payload = {
        "model": settings.minimax_model,
        "messages": [
            {
                "role": "system",
                "content": "你是邮件重要性分类助手。只输出一个 JSON 对象，不要多余文字。",
            },
            {
                "role": "user",
                "content": (
                    "邮件如下：\n"
                    "主题：【双十一狂欢】全场5折，点击退订\n"
                    "发件人：promo@shop.example.com\n"
                    "正文：亲爱的用户，大促来袭……如需退订请点击链接。\n\n"
                    "请判断是否重要，返回 JSON："
                    '{"is_important": bool, "confidence": 0~1, "reason": "简短中文", '
                    '"category": "工作/账单/社交/营销/垃圾 之一"}'
                ),
            },
        ],
        "temperature": 0.1,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    print(f"→ 调用 {url}")
    print(f"   模型: {settings.minimax_model}")
    try:
        with httpx.Client(timeout=60) as client:
            resp = client.post(url, headers=headers, json=payload)
    except Exception as exc:  # noqa: BLE001
        print(f"❌ MiniMax 命脉 FAIL：请求异常 {type(exc).__name__}: {exc}")
        return 1

    print(f"\nHTTP 状态: {resp.status_code}")

    # 打印限流相关响应头（若服务端返回）
    rl_headers = {k: v for k, v in resp.headers.items() if "limit" in k.lower()}
    if rl_headers:
        print("限流相关响应头:")
        for k, v in rl_headers.items():
            print(f"   {k}: {v}")

    try:
        data = resp.json()
    except json.JSONDecodeError:
        print(f"❌ 响应非 JSON：{resp.text[:500]}")
        return 1

    base = data.get("base_resp", {}) or {}
    status_code = base.get("status_code")
    print(f"base_resp: status_code={status_code}, status_msg={base.get('status_msg')!r}")

    choices = data.get("choices")
    if resp.status_code == 200 and status_code == 0 and choices:
        content = choices[0].get("message", {}).get("content", "")
        print("\n模型返回内容:")
        print(content)
        print(f"\nusage: {data.get('usage')}")
        print("\n✅ MiniMax 命脉 PASS：订阅 Key 可用于程序化调用。")
        return 0

    # 失败：给出定位提示
    print("\n❌ MiniMax 命脉 FAIL")
    if status_code in HINTS:
        print(f"   提示: {HINTS[status_code]}")
    print(f"   完整响应(截断): {json.dumps(data, ensure_ascii=False)[:800]}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
