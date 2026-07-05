"""Winnow 命令行入口。

    winnow run                          启动收信常驻服务（IMAP IDLE）
    winnow once [--backfill N] [--dry-run]
                                        跑一轮：处理新邮件；--backfill 回捞最近 N 封演练；
                                        --dry-run 只判断不实际转发
    winnow logs [--limit N]             打印最近的处理记录
    winnow set-password [--username admin] [--password ...]
                                        设置控制台登录密码（不带 --password 则交互式输入）
    winnow web [--host 0.0.0.0] [--port 8000]
                                        启动 Web 控制台（FastAPI + 内置前端）

用法：uv run winnow <cmd>
"""

from __future__ import annotations

import argparse
import getpass
import logging

from sqlalchemy import desc
from sqlmodel import select

from app.config import require, settings
from app.db import get_or_create_primary_account, init_db, session_scope
from app.models import ProcessedEmail, User
from app.security import hash_password
from app.service import AccountWorker, _get_last_seen, _update_last_seen, run


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )


def _require_core_config() -> None:
    require(settings.email_126, "EMAIL_126")
    require(settings.imap_auth_code, "IMAP_AUTH_CODE")
    require(settings.minimax_api_key, "MINIMAX_API_KEY")
    require(settings.forward_to, "FORWARD_TO")


def cmd_run(_args: argparse.Namespace) -> int:
    _require_core_config()
    run()
    return 0


def cmd_once(args: argparse.Namespace) -> int:
    _require_core_config()
    init_db()
    account = get_or_create_primary_account(settings.email_126)
    worker = AccountWorker(settings, account)
    worker.imap.connect()
    try:
        if args.backfill:
            messages = worker.imap.fetch_last(args.backfill)
            print(f"回捞最近 {len(messages)} 封演练（dry_run={args.dry_run}）：")
            worker.process_batch(messages, dry_run=args.dry_run, advance_uid=False)
        else:
            if _get_last_seen(account.id) is None:
                max_uid = worker.imap.get_max_uid()
                _update_last_seen(account.id, max_uid or 0)
                print(f"首次运行：已设基线 last_seen_uid={max_uid or 0}，未处理旧邮件。")
                print("给该 126 邮箱发一封新邮件后再次运行 `winnow once` 即可看到处理。")
                return 0
            worker._process_new()
            print("已处理本轮新邮件（详见日志/`winnow logs`）。")
    finally:
        worker.imap.disconnect()
    return 0


def cmd_logs(args: argparse.Namespace) -> int:
    init_db()
    with session_scope() as s:
        rows = s.exec(
            select(ProcessedEmail).order_by(desc(ProcessedEmail.id)).limit(args.limit)
        ).all()
    if not rows:
        print("暂无处理记录。")
        return 0
    print(f"最近 {len(rows)} 条处理记录：")
    print("-" * 100)
    for r in rows:
        status = " ".join([
            "预筛" if r.prefiltered else "AI",
            "重要" if r.is_important else "非重要",
            "已转发" if r.forwarded else "未转发",
        ])
        print(f"#{r.id} [{status}] conf={r.confidence:.2f} 类别={r.category}")
        print(f"   来自: {r.from_addr}")
        print(f"   主题: {r.subject}")
        print(f"   理由: {r.reason}")
        if r.error:
            print(f"   备注: {r.error}")
        print("-" * 100)
    return 0


def cmd_set_password(args: argparse.Namespace) -> int:
    init_db()
    username = args.username
    if args.password:
        password = args.password
    else:
        password = getpass.getpass(f"为用户 {username} 设置控制台密码: ")
        if password != getpass.getpass("再输一次确认: "):
            print("两次输入不一致，未修改。")
            return 1
    if not password:
        print("密码不能为空。")
        return 1
    with session_scope() as s:
        user = s.exec(select(User).where(User.username == username)).first()
        if user is None:
            # CLI 创建的用户视为运维方，直接给管理员
            s.add(User(username=username, password_hash=hash_password(password), is_admin=True))
        else:
            user.password_hash = hash_password(password)
    from app.db import claim_orphan_accounts

    claim_orphan_accounts()
    print(f"✅ 已设置用户 {username} 的登录密码。")
    return 0


def cmd_web(args: argparse.Namespace) -> int:
    import uvicorn

    init_db()
    uvicorn.run("app.web.main:app", host=args.host, port=args.port, reload=False)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="winnow", description="126 邮箱 AI 智能转发服务")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="启动收信常驻服务（IMAP IDLE）")
    p_run.set_defaults(func=cmd_run)

    p_once = sub.add_parser("once", help="跑一轮（处理新邮件 / 回捞演练）")
    p_once.add_argument("--backfill", type=int, default=0, metavar="N", help="回捞最近 N 封演练")
    p_once.add_argument("--dry-run", action="store_true", help="只判断不实际转发")
    p_once.set_defaults(func=cmd_once)

    p_logs = sub.add_parser("logs", help="打印最近处理记录")
    p_logs.add_argument("--limit", type=int, default=20, help="显示条数")
    p_logs.set_defaults(func=cmd_logs)

    p_pw = sub.add_parser("set-password", help="设置控制台登录密码")
    p_pw.add_argument("--username", default="admin")
    p_pw.add_argument("--password", default=None, help="非交互式传入（省略则交互输入）")
    p_pw.set_defaults(func=cmd_set_password)

    p_web = sub.add_parser("web", help="启动 Web 控制台")
    p_web.add_argument("--host", default="0.0.0.0")
    p_web.add_argument("--port", type=int, default=8000)
    p_web.set_defaults(func=cmd_web)
    return parser


def main() -> int:
    _setup_logging()
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
