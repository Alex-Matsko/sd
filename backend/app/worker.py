"""Background worker (`python -m app.worker`, own container in docker-compose):
runs the SLA escalation sweep every `worker_interval_seconds`, and polls the
support mailbox on its own cadence (section 2.3: "интервал ≤ 60 сек"),
independently configurable from Настройки → Каналы since it's stored in
`integration_settings`, not `.env` - see services/integration_settings.py.
Errors are logged and the loop continues - on boot the app container may
still be applying migrations, so the first sweeps are allowed to fail."""

import time
import traceback

from app.config import settings
from app.db import SessionLocal
from app.services import email_channel, sla

TICK_SECONDS = 5
EMAIL_POLL_FALLBACK_SECONDS = 30  # used while the email channel isn't configured/enabled


def run_sla_sweep() -> int:
    db = SessionLocal()
    try:
        return sla.run_escalations(db)
    finally:
        db.close()


def run_email_poll() -> tuple[int, int]:
    """Returns (messages processed, seconds until the next poll)."""
    db = SessionLocal()
    try:
        config = email_channel.load_email_config(db)
        if config is None:
            return 0, EMAIL_POLL_FALLBACK_SECONDS
        return email_channel.poll_inbox(db, config), config.poll_interval_seconds
    finally:
        db.close()


def main() -> None:
    print(
        f"[worker] SLA-эскалации каждые {settings.worker_interval_seconds} с; "
        "опрос почты — интервал из Настроек → Каналы",
        flush=True,
    )
    next_sla_run = 0.0
    next_email_poll = 0.0
    while True:
        now = time.monotonic()

        if now >= next_sla_run:
            try:
                touched = run_sla_sweep()
                if touched:
                    print(f"[worker] эскалации: обновлено заявок - {touched}", flush=True)
            except Exception:
                traceback.print_exc()
            next_sla_run = now + settings.worker_interval_seconds

        if now >= next_email_poll:
            interval = EMAIL_POLL_FALLBACK_SECONDS
            try:
                processed, interval = run_email_poll()
                if processed:
                    print(f"[worker] почта: обработано писем - {processed}", flush=True)
            except Exception:
                traceback.print_exc()
            next_email_poll = now + interval

        time.sleep(TICK_SECONDS)


if __name__ == "__main__":
    main()
