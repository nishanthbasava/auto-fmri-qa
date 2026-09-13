"""Audit trail: one immutable row per meaningful action."""
from __future__ import annotations

from fastapi import Request
from sqlalchemy.orm import Session

from ..db.models import AuditEvent


def client_ip(request: Request | None) -> str | None:
    if request is None:
        return None
    fwd = request.headers.get("x-forwarded-for")     # nginx / Cloud Run put the real IP here
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None


def record(db: Session, actor: str | None, action: str, target: str | None = None,
           detail: dict | None = None, request: Request | None = None) -> AuditEvent:
    ev = AuditEvent(actor=actor, action=action, target=target, detail=detail,
                    ip=client_ip(request))
    db.add(ev)
    db.flush()
    return ev
