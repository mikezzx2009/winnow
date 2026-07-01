"""命脉脚本 (a): 验证 126 IMAP 收信链路。

重点验证：
  1. 用「授权码」通过 IMAP 登录 imap.126.com。
  2. 登录后立刻发送 IMAP ID 命令声明客户端身份 —— 否则网易报 "Unsafe Login"。
     (Python 标准库 imaplib 无原生 ID 命令，这里手动注册并发送，符合 RFC 2971。)
  3. 选择 INBOX，拉取最新 5 封邮件的「邮件头」(不下载正文，保护隐私)。

运行：
    uv run python scripts/check_imap.py

预期 PASS：能打印出最新几封邮件的 UID / 日期 / 发件人 / 主题，且无 "Unsafe Login" 报错。
本脚本只读，不修改任何邮件状态 (mark_seen=False)、不打印正文。
"""

import imaplib
import sys
from pathlib import Path

# 让脚本无论从哪个目录运行都能 import app.*
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from imap_tools import MailBox  # noqa: E402

from app.config import require, settings  # noqa: E402


def send_imap_id(client: imaplib.IMAP4, contact: str) -> None:
    """向网易 IMAP 发送 ID 命令，声明客户端身份，规避 "Unsafe Login"。

    imaplib 未内置 ID 命令，需先把它注册为合法命令，再用底层 _simple_command 发送。
    """
    imaplib.Commands["ID"] = ("AUTH", "SELECTED", "NONAUTH")
    fields = {
        "name": "Winnow",
        "version": "1.0.0",
        "vendor": "Winnow Mail Forwarder",
        "contact": contact,
    }
    tokens = []
    for key, value in fields.items():
        tokens.append(f'"{key}"')
        tokens.append(f'"{value}"')
    arg = "(" + " ".join(tokens) + ")"
    client._simple_command("ID", arg)  # type: ignore[attr-defined]


def main() -> int:
    email = require(settings.email_126, "EMAIL_126")
    auth_code = require(settings.imap_auth_code, "IMAP_AUTH_CODE")

    print(f"→ 连接 {settings.imap_host}:{settings.imap_port} (SSL) ...")
    mailbox = MailBox(settings.imap_host, port=settings.imap_port)
    try:
        # initial_folder=None: 先只登录、不选文件夹，好在 SELECT 之前插入 ID 命令。
        mailbox.login(email, auth_code, initial_folder=None)
        print("✅ LOGIN 成功")

        send_imap_id(mailbox.client, email)
        print("✅ 已发送 ID 命令 (规避 Unsafe Login)")

        mailbox.folder.set("INBOX")
        print("✅ 已选择 INBOX")

        print("\n最新 5 封邮件 (仅邮件头, 不含正文):")
        print("-" * 72)
        count = 0
        for msg in mailbox.fetch(
            reverse=True, limit=5, mark_seen=False, headers_only=True, bulk=True
        ):
            count += 1
            has_unsub = "是" if msg.headers.get("list-unsubscribe") else "否"
            print(f"[{count}] UID={msg.uid}  {msg.date_str}")
            print(f"    发件人: {msg.from_}")
            print(f"    主  题: {msg.subject}")
            print(f"    含退订头(List-Unsubscribe): {has_unsub}  ← 预筛的营销信号之一")
        print("-" * 72)
        print(f"\n✅ IMAP 命脉 PASS：成功读取 {count} 封邮件头。")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"\n❌ IMAP 命脉 FAIL：{type(exc).__name__}: {exc}")
        print("   排查：授权码是否正确 / 是否已在网页端开启 IMAP 服务 / ID 命令是否生效。")
        return 1
    finally:
        try:
            mailbox.logout()
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    raise SystemExit(main())
