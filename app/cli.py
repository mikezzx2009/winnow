"""Winnow 命令行入口（Phase 1 的最简界面）。

    winnow run                         启动常驻服务（IMAP IDLE 实时收信）
    winnow once [--backfill N] [--dry-run]
                                       跑一轮：处理新邮件；--backfill 回捞最近 N 封演练；
                                       --dry-run 只判断不实际转发
    winnow logs [--limit N]            打印最近的处理记录

用法：uv run winnow <cmd>  或  uv run python -m app.cli <cmd>
"""

from __future__ import annotations

import argparse
import logging

from sqlalchemy import desc
from sqlmodel import select

from app.config import require, settings
from app.db import ensure_account, init_db, session_scope
from app.models import ProcessedEmail
from app.pipeline import process_message
from app.service import WinnowService, _get_last_seen, _update_last_seen, run


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


def cmd_run(_args: argparse.Namespace) -> int:
    _require_core_config()
    run()
    return 0


def cmd_once(args: argparse.Namespace) -> int:
    _require_core_config()
    init_db()
    account = ensure_account(settings.email_126)
    svc = WinnowService(settings)
    svc.imap.connect()
    try:
        if args.backfill:
            messages = svc.imap.fetch_last(args.backfill)
            print(f"回捞最近 {len(messages)} 封演练（dry_run={args.dry_run}）：")
            for msg in messages:
                with session_scope() as s:
                    process_message(
                        s, account, msg,
                        analyzer=svc.analyzer, forwarder=svc.forwarder,
                        settings=settings, dry_run=args.dry_run,
                    )
        else:
            if _get_last_seen(account.id) is None:
                max_uid = svc.imap.get_max_uid()
                _update_last_seen(account.id, max_uid or 0)
                print(f"首次运行：已设基线 last_seen_uid={max_uid or 0}，未处理旧邮件。")
                print("给该 126 邮箱发一封新邮件后再次运行 `winnow once` 即可看到处理。")
                return 0
            svc._process_new(account)
            print("已处理本轮新邮件（详见日志/`winnow logs`）。")
    finally:
        svc.imap.disconnect()
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
        flags = []
        flags.append("预筛" if r.prefiltered else "AI")
        flags.append("重要" if r.is_important else "非重要")
        flags.append("已转发" if r.forwarded else "未转发")
        status = " ".join(flags)
        print(f"#{r.id} [{status}] conf={r.confidence:.2f} 类别={r.category}")
        print(f"   来自: {r.from_addr}")
        print(f"   主题: {r.subject}")
        print(f"   理由: {r.reason}")
        if r.error:
            print(f"   备注: {r.error}")
        print("-" * 100)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="winnow", description="126 邮箱 AI 智能转发服务")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="启动常驻服务（IMAP IDLE）")
    p_run.set_defaults(func=cmd_run)

    p_once = sub.add_parser("once", help="跑一轮（处理新邮件 / 回捞演练）")
    p_once.add_argument("--backfill", type=int, default=0, metavar="N", help="回捞最近 N 封演练")
    p_once.add_argument("--dry-run", action="store_true", help="只判断不实际转发")
    p_once.set_defaults(func=cmd_once)

    p_logs = sub.add_parser("logs", help="打印最近处理记录")
    p_logs.add_argument("--limit", type=int, default=20, help="显示条数")
    p_logs.set_defaults(func=cmd_logs)
    return parser


def main() -> int:
    _setup_logging()
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
