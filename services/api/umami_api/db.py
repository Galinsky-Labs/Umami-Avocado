"""SQLAlchemy engine/session management. One engine per application instance."""
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


def utcnow() -> datetime:
    return datetime.now(UTC)


def make_engine(url: str) -> Engine:
    # prepare_threshold=None keeps psycopg compatible with transaction-mode poolers (Neon -pooler).
    return create_engine(
        url, pool_pre_ping=True, pool_size=5, max_overflow=5, pool_recycle=300,
        connect_args={"prepare_threshold": None, "connect_timeout": 10},
    )


class Database:
    def __init__(self, url: str):
        self.engine = make_engine(url)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    @contextmanager
    def session(self) -> Iterator[Session]:
        with self.sessions() as session:
            try:
                yield session
                session.commit()
            except BaseException:
                session.rollback()
                raise

    def ping(self) -> bool:
        try:
            with self.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return True
        except Exception:  # noqa: BLE001 - readiness reports, never raises
            return False

    def dispose(self) -> None:
        self.engine.dispose()
