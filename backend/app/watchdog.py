"""Independent supervisor: reports a stopped worker even if all worker threads died."""
from datetime import datetime, timezone
import shutil
import time
import traceback
from pathlib import Path

from app.config import settings
from app.db import SessionLocal
from app.models.channel_job import WorkerPulse
from app.models.notification import Notification
from app.core.enums import NotificationType
from app.services import worker_health
from app.services.channel_queue import ChannelFailure, notify_operators


def sweep(db, alert_missing=True):
    try:
        directory = Path(settings.attachments_dir)
        directory.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(directory).free < settings.min_free_attachment_mb * 1024 * 1024:
            raise ChannelFailure("В хранилище вложений заканчивается свободное место")
        worker_health.pulse(db, "storage", success=True, interval=30)
    except Exception as error:
        worker_health.pulse(db, "storage", error=error, interval=30)
    worker_health.pulse(db, "watchdog", success=True, interval=30)
    for row in worker_health.snapshot(db):
        if row["state"] != "stale" and not (alert_missing and row["state"] == "missing"):
            continue
        title = f"Нет сигнала фоновой обработки: {row['component']}"
        last = max((value for value in [row["started_at"], row["succeeded_at"], row["failed_at"]] if value), default=None)
        query = db.query(Notification).filter(Notification.type == NotificationType.CHANNEL_ERROR, Notification.title == title)
        if last:
            query = query.filter(Notification.created_at >= last)
        if not query.first():
            notify_operators(db, title)
    db.commit()


def main():
    started = time.monotonic()
    while True:
        try:
            with SessionLocal() as db:
                sweep(db, alert_missing=time.monotonic() - started >= 60)
            Path("/tmp/sd-watchdog-heartbeat").write_text(str(time.time()))
        except Exception:
            traceback.print_exc()
        time.sleep(15)


if __name__ == "__main__":
    main()
