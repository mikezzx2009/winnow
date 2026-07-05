"""数据库引擎与会话。Phase 1 用 SQLite，便于以后换 Postgres（只改 DATABASE_URL）。"""

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine, select

from app.config import settings
from app.models import Account  # noqa: F401  (确保建表时模型已注册)
from app.models import ProcessedEmail  # noqa: F401

# SQLite 需要 check_same_thread=False，以便多账号 worker 线程与 Web 进程共享连接。
_is_sqlite = settings.database_url.startswith("sqlite")
_connect_args = {"check_same_thread": False} if _is_sqlite else {}
engine = create_engine(settings.database_url, echo=False, connect_args=_connect_args)

if _is_sqlite:
    # WAL 模式 + busy_timeout：降低多线程/多进程并发写时的 "database is locked"。
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()


def init_db() -> None:
    """建表 + 轻量迁移（均幂等）。"""
    SQLModel.metadata.create_all(engine)
    if _is_sqlite:
        _migrate_sqlite()


def _migrate_sqlite() -> None:
    """SQLite 轻量迁移：create_all 不会给已有表加列，这里手动补。"""
    with engine.connect() as conn:
        def columns(table: str) -> list:
            return [row[1] for row in conn.exec_driver_sql(f'PRAGMA table_info("{table}")')]

        if "is_admin" not in columns("user"):
            conn.exec_driver_sql('ALTER TABLE "user" ADD COLUMN is_admin BOOLEAN DEFAULT 0')
            # 既有用户（注册功能上线前创建的）一律视为管理员
            conn.exec_driver_sql('UPDATE "user" SET is_admin = 1')
        if "user_id" not in columns("account"):
            conn.exec_driver_sql("ALTER TABLE account ADD COLUMN user_id INTEGER")
            # 既有账号归给第一位用户（即管理员）
            conn.exec_driver_sql('UPDATE account SET user_id = (SELECT MIN(id) FROM "user")')
        conn.commit()


@contextmanager
def session_scope() -> Iterator[Session]:
    """事务性会话上下文：正常提交，异常回滚。"""
    # expire_on_commit=False：提交后仍可读取对象属性（供会话关闭后使用/打印）
    session = Session(engine, expire_on_commit=False)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def ensure_account(email: str) -> Account:
    """确保账号存在（幂等），返回该账号。"""
    with session_scope() as session:
        account = session.exec(select(Account).where(Account.email == email)).first()
        if account is None:
            account = Account(email=email)
            session.add(account)
            session.flush()
        session.refresh(account)
        # 分离出来给调用方使用（会话关闭后仍可读属性）
        session.expunge(account)
        return account


def get_primary_account():
    """返回主账号（Phase 1/2 单账号 = id 最小的一行），无则返回 None。"""
    with session_scope() as session:
        account = session.exec(select(Account).order_by(Account.id)).first()
        if account is not None:
            session.expunge(account)
        return account


def get_or_create_primary_account(default_email: str) -> Account:
    account = get_primary_account()
    if account is not None:
        return account
    # EMAIL_126 未配置时用占位地址，避免控制台首屏 500；用户可在绑定页改为真实地址
    account = ensure_account(default_email or "unconfigured@126.com")
    claim_orphan_accounts()
    return account


def claim_orphan_accounts() -> None:
    """把无归属（user_id 为空）的账号归给第一位管理员（若存在）。幂等。"""
    from app.models import User

    with session_scope() as session:
        admin = session.exec(
            select(User).where(User.is_admin == True).order_by(User.id)  # noqa: E712
        ).first()
        if admin is None:
            return
        orphans = session.exec(select(Account).where(Account.user_id == None)).all()  # noqa: E711
        for acc in orphans:
            acc.user_id = admin.id
            session.add(acc)
