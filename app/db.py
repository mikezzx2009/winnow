"""数据库引擎与会话。Phase 1 用 SQLite，便于以后换 Postgres（只改 DATABASE_URL）。"""

from contextlib import contextmanager
from typing import Iterator

from sqlmodel import Session, SQLModel, create_engine, select

from app.config import settings
from app.models import Account  # noqa: F401  (确保建表时模型已注册)
from app.models import ProcessedEmail  # noqa: F401

# SQLite 需要 check_same_thread=False，以便 IDLE 线程与主线程共享连接。
_connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, echo=False, connect_args=_connect_args)


def init_db() -> None:
    """建表（幂等）。"""
    SQLModel.metadata.create_all(engine)


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
