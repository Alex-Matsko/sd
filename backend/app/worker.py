"""Background worker (`python -m app.worker`, own container in docker-compose):
runs the SLA escalation sweep every `worker_interval_seconds`, polls the
support mailbox on its own cadence, and long-polls MAX in a dedicated thread.
All three are independently configurable from Настройки → Каналы (except the
SLA interval, which stays in `.env` as an infrastructure-level knob) - see
services/integration_settings.py. Errors are logged and each loop continues -
on boot the app container may still be applying migrations, so the first
sweeps are allowed to fail.

MAX runs in its own thread rather than the main tick loop because its
long-poll (GET /updates) blocks server-side for up to `poll_timeout_seconds`;
interleaving that with the SLA/email ticks on one thread would stall SLA
escalations for the length of every poll.
"""

import threading
import time
import traceback

from app.config import settings
from app.db import SessionLocal
from app.services import email_channel, max_channel, sla

TICK_SECONDS = 5
EMAIL_POLL_FALLBACK_SECONDS = 30  # used while the email channel isn't configured/enabled
MAX_IDLE_RETRY_SECONDS = 10  # used while the MAX channel isn't configured/enabled


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


def run_max_poll_once() -> int:
    db = SessionLocal()
    try:
        config = max_channel.load_max_config(db)
        if config is None:
            return -1  # signals "not configured" to the poller loop below
        return max_channel.poll_updates(db, config)
    finally:
        db.close()


def max_poller_loop() -> None:
    print("[worker] поток MAX запущен", flush=True)
    while True:
        try:
            processed = run_max_poll_once()
            if processed == -1:
                time.sleep(MAX_IDLE_RETRY_SECONDS)
            elif processed > 0:
                print(f"[worker] MAX: обработано обновлений - {processed}", flush=True)
        except Exception:
            traceback.print_exc()
            time.sleep(MAX_IDLE_RETRY_SECONDS)


def main() -> None:
    print(
        f"[worker] SLA-эскалации каждые {settings.worker_interval_seconds} с; "
        "опрос почты и MAX — интервалы из Настроек → Каналы",
        flush=True,
    )
    threading.Thread(target=max_poller_loop, daemon=True).start()

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
