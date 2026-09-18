from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

ROLES = ("viewer", "reviewer", "admin")          # ordered: each includes the previous
DECISIONS = ("keep", "drop", "clear")

# JSON on SQLite, JSONB on Postgres (indexable, binary) -- same column definition.
JSONType = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="viewer")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    decisions: Mapped[list[Decision]] = relationship(back_populates="user")

    def can(self, role: str) -> bool:
        """Role hierarchy: admin > reviewer > viewer."""
        return self.active and ROLES.index(self.role) >= ROLES.index(role)


class Decision(Base):
    """Append-only. The current decision for a scan is the latest row; a
    'clear' row un-decides it. Nothing here is ever UPDATEd or DELETEd."""
    __tablename__ = "decisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(128), index=True)
    scan_key: Mapped[str] = mapped_column(String(128))
    decision: Mapped[str] = mapped_column(String(8))
    note: Mapped[str] = mapped_column(Text, default="")
    status_at_decision: Mapped[str | None] = mapped_column(String(16), nullable=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship(back_populates="decisions")

    __table_args__ = (Index("ix_decisions_run_scan", "run_id", "scan_key"),)

    def as_dict(self) -> dict:
        return {"id": self.id, "decision": self.decision, "note": self.note,
                "status_at_decision": self.status_at_decision,
                "by": self.user.username if self.user else None,
                "at": self.created_at.isoformat(timespec="seconds")}


class Job(Base):
    """One row per background job, updated in place (not append-only: phase and
    returncode change as the job runs). A row left running by a process that no
    longer exists (API restart) is detected via host_pid and marked interrupted
    on the next read, so job status survives restarts instead of vanishing with
    the in-process dict."""
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(128), index=True)
    phase: Mapped[str] = mapped_column(String(32), default="starting")
    returncode: Mapped[int | None] = mapped_column(Integer, nullable=True)
    host_pid: Mapped[int] = mapped_column(Integer)
    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def as_dict(self) -> dict:
        return {"phase": self.phase, "returncode": self.returncode,
                "started_at": self.started_at.isoformat(timespec="seconds")}


class AuditEvent(Base):
    """Who did what, to what, when, from where. Append-only."""
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    actor: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(48), index=True)
    target: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
    detail: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)

    def as_dict(self) -> dict:
        return {"id": self.id, "ts": self.ts.isoformat(timespec="seconds"), "actor": self.actor,
                "action": self.action, "target": self.target, "detail": self.detail, "ip": self.ip}
