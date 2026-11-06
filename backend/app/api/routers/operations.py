import json
from datetime import datetime
from pathlib import Path
import tempfile
import shutil

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_manager_or_above
from app.config import settings
from app.db import get_db
from app.models.channel_job import ChannelJob
from app.models.user import User
from app.services import audit, channel_queue, worker_health

router = APIRouter(tags=["operations"])


def _read(job):
    source_available = job.kind == "inbound" and not job.payload.get("_source_expired") and (job.raw_body is not None or job.channel != "email")
    return {"source_available": source_available, "summary": job.payload.get("_sd_summary", ""), "id": job.id, "kind": job.kind, "channel": job.channel, "state": job.state,
            "attempts": job.attempts, "last_error": job.last_error, "ticket_id": job.ticket_id,
            "message_id": job.message_id, "created_at": job.created_at, "available_at": job.available_at,
            "completed_at": job.completed_at}


@router.get("/operations/status")
def get_status(db: Session = Depends(get_db), _: User = Depends(require_manager_or_above)):
    counts = db.query(ChannelJob.kind, ChannelJob.state, func.count(ChannelJob.id)).group_by(ChannelJob.kind, ChannelJob.state).all()
    try:
        storage_free = shutil.disk_usage(settings.attachments_dir).free
    except OSError:
        storage_free = None
    return {"storage_free_bytes": storage_free, "workers": worker_health.snapshot(db),
            "queues": {kind: {state: count for k, state, count in counts if k == kind} for kind in ("inbound", "outbound")}}


@router.get("/operations/jobs")
def list_jobs(response: Response, kind: str | None = None, errors_only: bool = True, limit: int = 50, offset: int = 0,
              db: Session = Depends(get_db), _: User = Depends(require_manager_or_above)):
    if kind is not None and kind not in ("inbound", "outbound"):
        raise HTTPException(status_code=400, detail="Неизвестная очередь")
    query = db.query(ChannelJob)
    if kind:
        query = query.filter(ChannelJob.kind == kind)
    if errors_only:
        query = query.filter(ChannelJob.state.in_(["failed", "retry"]))
    response.headers["X-Total-Count"] = str(query.count())
    return [_read(job) for job in query.order_by(ChannelJob.id.desc()).offset(max(0, offset)).limit(max(1, min(200, limit)))]


@router.get("/operations/jobs/{job_id}/source")
def download_source(job_id: int, db: Session = Depends(get_db), _: User = Depends(require_manager_or_above)):
    job = db.get(ChannelJob, job_id)
    if job is None or job.kind != "inbound":
        raise HTTPException(status_code=404, detail="Исходное событие не найдено")
    if job.payload.get("_source_expired") or (job.raw_body is None and job.channel == "email") or (not job.payload and job.raw_body is None):
        raise HTTPException(status_code=410, detail="Истёк срок хранения исходного события")
    content = job.raw_body if job.raw_body is not None else json.dumps(job.payload, ensure_ascii=False).encode()
    suffix = "eml" if job.channel == "email" else "json"
    return Response(content=content, media_type="application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="event-{job.id}.{suffix}"'})


@router.post("/operations/jobs/{job_id}/retry")
def retry_job(job_id: int, db: Session = Depends(get_db), actor: User = Depends(require_manager_or_above)):
    job = db.query(ChannelJob).filter_by(id=job_id).with_for_update(skip_locked=True).first()
    if job is None:
        if db.query(ChannelJob.id).filter_by(id=job_id).first():
            raise HTTPException(status_code=409, detail="Событие сейчас обрабатывается")
        raise HTTPException(status_code=404, detail="Событие не найдено")
    if job.state not in ("retry", "failed"):
        raise HTTPException(status_code=409, detail="Событие уже обрабатывается или завершено")
    audit.record(db, entity_type="channel_job", entity_id=job.id, action="retry", user_id=actor.id, changes={"state": job.state})
    channel_queue.retry(db, job)
    return _read(job)


class DiscardRequest(BaseModel):
    reason: str = Field(min_length=5, max_length=500)


@router.post("/operations/jobs/{job_id}/discard")
def discard_job(job_id: int, payload: DiscardRequest, db: Session = Depends(get_db), actor: User = Depends(require_manager_or_above)):
    job = db.query(ChannelJob).filter_by(id=job_id).with_for_update(skip_locked=True).first()
    if job is None:
        if db.query(ChannelJob.id).filter_by(id=job_id).first():
            raise HTTPException(status_code=409, detail="Событие сейчас обрабатывается")
        raise HTTPException(status_code=404, detail="Событие не найдено")
    if job.state not in ("retry", "failed", "pending"):
        raise HTTPException(status_code=409, detail="Нельзя пропустить обрабатываемое или завершённое событие")
    if len(payload.reason.strip()) < 5:
        raise HTTPException(status_code=422, detail="Укажите содержательную причину пропуска")
    audit.record(db, entity_type="channel_job", entity_id=job.id, action="discard", user_id=actor.id,
                 changes={"reason": payload.reason, "state": job.state})
    job.state, job.lease_until, job.lease_token = "discarded", None, None
    job.completed_at = channel_queue.now()
    db.commit()
    return _read(job)


@router.get("/health/ready")
def readiness(response: Response, db: Session = Depends(get_db)):
    try:
        db.execute(select(1))
        directory = Path(settings.attachments_dir)
        directory.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(directory).free < settings.min_free_attachment_mb * 1024 * 1024:
            raise OSError("storage is full")
        with tempfile.TemporaryFile(dir=directory):
            pass
    except Exception:
        response.status_code = 503
        return {"status": "unavailable"}
    return {"status": "ok"}


@router.get("/health/worker")
def worker_readiness(response: Response, db: Session = Depends(get_db)):
    try:
        ok = worker_health.healthy(db)
    except Exception:
        ok = False
    if not ok:
        response.status_code = 503
    return {"status": "ok" if ok else "unavailable"}
