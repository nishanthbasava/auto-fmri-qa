"""Engine + session factory. DATABASE_URL picks the backend:

    sqlite:////abs/path/autoqa.db                 (default: <AFQ_RUNS>/autoqa.db)
    postgresql+psycopg://user:pw@host:5432/autoqa (lab / cloud)
"""
from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

_engine = None
_Session = None


def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    runs = os.environ.get("AFQ_RUNS", os.path.join(os.getcwd(), "runs"))
    os.makedirs(runs, exist_ok=True)
    return "sqlite:///" + os.path.join(os.path.abspath(runs), "autoqa.db")


def engine():
    global _engine, _Session
    url = database_url()
    if _engine is None or str(_engine.url) != url:
        kw = {"pool_pre_ping": True}
        if url.startswith("sqlite"):
            kw["connect_args"] = {"check_same_thread": False}
        _engine = create_engine(url, **kw)
        if url.startswith("sqlite"):
            @event.listens_for(_engine, "connect")
            def _fk_on(dbapi_conn, _record):      # SQLite ignores FKs unless told
                dbapi_conn.execute("PRAGMA foreign_keys=ON")
        _Session = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def reset() -> None:
    """Drop the cached engine (tests switch DATABASE_URL between cases)."""
    global _engine, _Session
    if _engine is not None:
        _engine.dispose()
    _engine = _Session = None


@contextmanager
def session() -> Iterator[Session]:
    engine()
    s = _Session()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def get_session() -> Iterator[Session]:
    """FastAPI dependency."""
    with session() as s:
        yield s
