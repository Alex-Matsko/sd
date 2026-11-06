"""Background worker (`python -m app.worker`, own container in docker-compose):
runs the SLA escalation sweep every `worker_interval_seconds`, polls the
support mailbox on its own cadence, and long-polls MAX and Telegram each in
their own dedicated thread. All are independently configurable from
Настройки → Каналы (except the SLA interval, which stays in `.env` as an
infrastructure-level knob) - see services/integration_settings.py. Errors are
logged and each loop continues - on boot the app container may still be
applying migrations, so the first sweeps are allowed to fail.

MAX/Telegram each run in their own thread rather than the main tick loop
because their long-poll (GET /updates / getUpdates) blocks server-side for
up to `poll_timeout_seconds`; interleaving that with the SLA/email ticks on
one thread would stall SLA escalations for the length of every poll.
"""

import threading
import time
import traceback

from app.config import settings, warn_about_insecure_settings
from app.core.enums import Channel
from app.db import SessionLocal
from app.services import settings_audit  # noqa: F401 — подключает слушатель аудита настроек
from app.services import (
    automation,
    channel_queue,
    worker_health,
    integration_settings,
    client_reports,
    email_channel,
    max_channel,
    schedules,
    sla,
    telegram_channel,
)

TICK_SECONDS = 5
EMAIL_POLL_FALLBACK_SECONDS = 30  # used while the email channel isn't configured/enabled
MAX_IDLE_RETRY_SECONDS = 10  # used while the MAX channel isn't configured/enabled
TELEGRAM_IDLE_RETRY_SECONDS = 10  # used while the Telegram channel isn't configured/enabled


def run_sla_sweep() -> int:
    db = SessionLocal()
    try:
        return sla.run_escalations(db)
    finally:
        db.close()


def run_automation_sweep() -> int:
    db = SessionLocal()
    try:
        return automation.run_automation_rules(db)
    finally:
        db.close()


def run_schedule_sweep() -> int:
    """Recurring planned tickets - checked on the SLA tick rather than on a
    timer of its own: schedules are day-granular, so a once-a-minute check is
    already far more precision than they need."""
    db = SessionLocal()
    try:
        return schedules.run_due_schedules(db)
    finally:
        db.close()


def run_monthly_client_reports() -> int:
    """Отчёты клиентам за прошлый месяц (ТЗ 9.2).

    Проверяется на том же тике, что и расписания, но фактическая работа
    делается один раз за месяц: если отчёты за прошлый месяц уже есть,
    проход ничего не создаёт. Отдельного планировщика ради этого заводить
    незачем, а привязка к «ровно 1-го числа в 00:00» сломалась бы от любого
    простоя воркера — здесь же отчёты сформируются при первом запуске после
    начала месяца.
    """
    db = SessionLocal()
    try:
        return client_reports.generate_monthly_reports(db)
    finally:
        db.close()


def check_disabled_channel(db, channel):
    setting = integration_settings.get(db, channel)
    if setting is not None and setting.is_enabled:
        raise channel_queue.ChannelFailure(f"Канал {channel.value} включён, но обязательные настройки не заполнены")


def run_email_poll() -> tuple[int, int, bool]:
    """Returns (messages processed, seconds until the next poll)."""
    db = SessionLocal()
    try:
        config = email_channel.load_email_config(db)
        if config is None:
            check_disabled_channel(db, Channel.EMAIL)
            return 0, EMAIL_POLL_FALLBACK_SECONDS, False
        return email_channel.poll_inbox(db, config), config.poll_interval_seconds, True
    finally:
        db.close()


def run_max_poll_once() -> int:
    db = SessionLocal()
    try:
        config = max_channel.load_max_config(db)
        if config is None:
            check_disabled_channel(db, Channel.MAX)
            return -1  # signals "not configured" to the poller loop below
        return max_channel.poll_updates(db, config)
    finally:
        db.close()


def observed(component, callback, interval=60, enabled=True):
    with SessionLocal() as db:
        worker_health.pulse(db, component, started=True, interval=interval, enabled=enabled)
    try:
        result = callback()
    except Exception as error:
        with SessionLocal() as db:
            worker_health.pulse(db, component, error=error, interval=interval, enabled=enabled)
        raise
    with SessionLocal() as db:
        worker_health.pulse(db, component, success=True, interval=interval,
                            enabled=enabled and result != -1)
    return result


def queue_loop(kind):
    component = "inbound" if kind == "inbound" else "outbound"
    while True:
        def run():
            with SessionLocal() as db:
                return channel_queue.run_batch(db, kind, limit=1)
        try:
            # One transport job can contain ten files, each with a bounded timeout.
            touched = observed(component, run, interval=300)
            time.sleep(0.2 if touched else TICK_SECONDS)
        except Exception:
            traceback.print_exc()
            time.sleep(TICK_SECONDS)


def max_poller_loop() -> None:
    print("[worker] поток MAX запущен", flush=True)
    while True:
        try:
            processed = observed("max", run_max_poll_once, interval=60)
            if processed == -1:
                time.sleep(MAX_IDLE_RETRY_SECONDS)
            elif processed > 0:
                print(f"[worker] MAX: обработано обновлений - {processed}", flush=True)
        except Exception:
            traceback.print_exc()
            time.sleep(MAX_IDLE_RETRY_SECONDS)


def run_telegram_poll_once() -> int:
    db = SessionLocal()
    try:
        config = telegram_channel.load_telegram_config(db)
        if config is None:
            check_disabled_channel(db, Channel.TELEGRAM)
            return -1  # signals "not configured" to the poller loop below
        return telegram_channel.poll_updates(db, config)
    finally:
        db.close()


def telegram_poller_loop() -> None:
    print("[worker] поток Telegram запущен", flush=True)
    while True:
        try:
            processed = observed("telegram", run_telegram_poll_once, interval=60)
            if processed == -1:
                time.sleep(TELEGRAM_IDLE_RETRY_SECONDS)
            elif processed > 0:
                print(f"[worker] Telegram: обработано обновлений - {processed}", flush=True)
        except Exception:
            traceback.print_exc()
            time.sleep(TELEGRAM_IDLE_RETRY_SECONDS)


def email_poller_loop():
    while True:
        interval = EMAIL_POLL_FALLBACK_SECONDS
        try:
            processed, interval, enabled = observed("email", run_email_poll, interval=300)
            if not enabled:
                with SessionLocal() as db:
                    worker_health.pulse(db, "email", success=True, enabled=False, interval=interval)
        except Exception:
            traceback.print_exc()
        time.sleep(interval)


def run_retention():
    with SessionLocal() as db:
        return channel_queue.prune_completed(db)


def main() -> None:
    warn_about_insecure_settings()
    print(
        f"[worker] SLA-эскалации каждые {settings.worker_interval_seconds} с; "
        "опрос почты, MAX и Telegram — интервалы из Настроек → Каналы",
        flush=True,
    )
    threading.Thread(target=max_poller_loop, daemon=True).start()
    threading.Thread(target=telegram_poller_loop, daemon=True).start()

    threading.Thread(target=queue_loop, args=("inbound",), daemon=True).start()
    threading.Thread(target=queue_loop, args=("outbound",), daemon=True).start()

    threading.Thread(target=email_poller_loop, daemon=True).start()

    next_sla_run = 0.0
    while True:
        now = time.monotonic()
        try:
            with SessionLocal() as db:
                worker_health.pulse(db, "main", success=True, interval=TICK_SECONDS)
        except Exception:
            traceback.print_exc()

        if now >= next_sla_run:
            try:
                touched = observed("sla", run_sla_sweep, interval=settings.worker_interval_seconds)
                if touched:
                    print(f"[worker] эскалации: обновлено заявок - {touched}", flush=True)
            except Exception:
                traceback.print_exc()
            try:
                closed = observed("automation", run_automation_sweep, interval=settings.worker_interval_seconds)
                if closed:
                    print(f"[worker] автоматизация: обновлено заявок - {closed}", flush=True)
            except Exception:
                traceback.print_exc()
            try:
                planned = observed("schedules", run_schedule_sweep, interval=settings.worker_interval_seconds)
                if planned:
                    print(f"[worker] расписания: создано плановых заявок - {planned}", flush=True)
            except Exception:
                traceback.print_exc()
            try:
                generated = observed("client_reports", run_monthly_client_reports, interval=settings.worker_interval_seconds)
                if generated:
                    print(f"[worker] отчёты клиентам: сформировано - {generated}", flush=True)
            except Exception:
                traceback.print_exc()
            try:
                observed("retention", run_retention, interval=settings.worker_interval_seconds)
            except Exception:
                traceback.print_exc()
            next_sla_run = now + settings.worker_interval_seconds

        time.sleep(TICK_SECONDS)


if __name__ == "__main__":
    main()
