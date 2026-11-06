"""Persistent heartbeats: a live API does not imply a healthy background worker."""
from datetime import datetime, timezone
from sqlalchemy.dialects.postgresql import insert
from app.models.channel_job import WorkerPulse
from app.services.channel_queue import notify_operators, safe_error

COMPONENTS = ("main", "inbound", "outbound", "email", "max", "telegram", "sla", "automation", "schedules", "client_reports", "retention", "storage", "watchdog")


def pulse(db, component, *, started=False, success=False, error=None, enabled=True, interval=60):
    clock = datetime.now(timezone.utc)
    values = {"component": component, "enabled": enabled, "expected_interval": interval}
    if started:
        values["started_at"] = clock
    if success:
        values.update(succeeded_at=clock, last_error=None)
    if error is not None:
        values.update(failed_at=clock, last_error=safe_error(error))
    previous = db.get(WorkerPulse, component)
    notify = error is not None and (previous is None or previous.last_error is None)
    stmt = insert(WorkerPulse).values(**values).on_conflict_do_update(
        index_elements=[WorkerPulse.component], set_={key: value for key, value in values.items() if key != "component"})
    db.execute(stmt)
    if notify:
        notify_operators(db, f"Фоновая обработка «{component}»: {values['last_error']}")
    db.commit()
    db.expire_all()


def snapshot(db, now=None):
    clock = now or datetime.now(timezone.utc)
    rows = {row.component: row for row in db.query(WorkerPulse)}
    result = []
    for component in COMPONENTS:
        row = rows.get(component)
        if row is None:
            result.append({"component": component, "state": "missing", "last_error": None,
                           "started_at": None, "succeeded_at": None, "failed_at": None})
            continue
        last = max((value for value in [row.started_at, row.succeeded_at, row.failed_at] if value), default=None)
        stale = last is None or (clock - last).total_seconds() > max(90, row.expected_interval * 3)
        state = "disabled" if not row.enabled else "stale" if stale else "error" if row.last_error else "ok"
        result.append({"component": component, "state": state, "last_error": row.last_error,
                       "started_at": row.started_at, "succeeded_at": row.succeeded_at, "failed_at": row.failed_at})
    return result


def healthy(db):
    return all(row["state"] in ("ok", "disabled") for row in snapshot(db))
