"""One-way sync: latest DB decisions -> runs/<run>/state.json.

The journal is what the deck builder and `autoqa audit surface` read, so after
a review session this copies each scan's current decision (and full history)
into it. Direction is always DB -> journal; the API never writes decisions to
the journal itself, so there is exactly one source of truth.
"""
from __future__ import annotations

import os

from sqlalchemy import select

from ..pipeline.state import RunState
from .models import Decision
from .session import session


def sync_journal(run_dir: str) -> int:
    run_id = os.path.basename(os.path.normpath(run_dir))
    state = RunState(run_dir)
    with session() as db:
        rows = db.scalars(select(Decision).where(Decision.run_id == run_id)
                          .order_by(Decision.id)).all()
        latest: dict[str, dict | None] = {}
        history: dict[str, list] = {}
        for d in rows:
            latest[d.scan_key] = None if d.decision == "clear" else d.as_dict()
            history.setdefault(d.scan_key, []).append(d.as_dict())
    n = 0
    for key, s in state.scans().items():
        if key in latest:
            s["decision"] = latest[key]
            s["decision_log"] = history[key]
            n += 1
    state.save()
    return n
