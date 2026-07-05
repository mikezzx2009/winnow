"""命脉脚本 (b): 验证 126 SMTP 发信链路。

以你的 126 身份，通过 smtp.126.com 发一封测试邮件到 FORWARD_TO 目标邮箱。
因为是真实登录 smtp.126.com 发出，SPF/DKIM 天然通过。

运行：
    uv run python scripts/check_smtp.py

预期 PASS：脚本打印发送成功，且你在目标邮箱 (FORWARD_TO) 收到这封测试信。
"""

import smtplib
import ssl
import sys
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import require, settings  # noqa: E402


def main() -> int:
    email = require(settings.email_126, "EMAIL_126")
    auth_code = require(settings.imap_auth_code, "IMAP_AUTH_CODE")
    target = require(settings.forward_to, "FORWARD_TO")

    msg = EmailMessage()
    msg["From"] = f"Winnow <{email}>"        # 发件人必须是登录账号本身，否则 126 拒发
    msg["To"] = target
    msg["Subject"] = f"{settings.subject_prefix}SMTP 命脉测试"
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="126.com")
    msg.set_content(
        "这是一封 Winnow SMTP 命脉测试邮件。\n"
        "若你在目标邮箱收到它，说明 126 SMTP 发信链路正常。\n"
    )

    print(f"→ 连接 {settings.smtp_host}:{settings.smtp_port} (SSL)，发信至 {target} ...")
    try:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(
            settings.smtp_host, settings.smtp_port, context=context, timeout=30
        ) as server:
            server.login(email, auth_code)
            server.send_message(msg)
        print("✅ SMTP 命脉 PASS：测试邮件已发出。")
        print(f"   请到 {target} 确认收到主题为 “{msg['Subject']}” 的邮件。")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"❌ SMTP 命脉 FAIL：{type(exc).__name__}: {exc}")
        print("   排查：授权码是否正确 / 是否已开启 SMTP 服务 / 是否触发发信频率限制。")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
