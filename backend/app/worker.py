"""Background worker (`python -m app.worker`, own container in docker-compose):
runs the SLA escalation sweep every `worker_interval_seconds`. Errors are logged
and the loop continues - on boot the app container may still be applying
migrations, so the first sweeps are allowed to fail."""

import time
import traceback

from app.config import settings
from app.db import SessionLocal
from app.services import sla


def run_once() -> int:
    db = SessionLocal()
    try:
        return sla.run_escalations(db)
    finally:
        db.close()


def main() -> None:
    print(f"[worker] SLA-эскалации, интервал {settings.worker_interval_seconds} с", flush=True)
    while True:
        try:
            touched = run_once()
            if touched:
                print(f"[worker] эскалации: обновлено заявок - {touched}", flush=True)
        except Exception:
            traceback.print_exc()
        time.sleep(settings.worker_interval_seconds)


if __name__ == "__main__":
    main()
