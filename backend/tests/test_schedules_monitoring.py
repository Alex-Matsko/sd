"""Recurring planned tickets and the monitoring integration (по запросу
заказчика, вне исходного ТЗ) - plus saved queue filters (ТЗ 8.1)."""

from datetime import date, datetime, timezone

import pytest
from fastapi import HTTPException, Response
from starlette.requests import Request

from app.api.deps import verify_webhook_secret
from sqlalchemy.orm import Session

from app.core.enums import Channel, Priority, ScheduleCadence, TicketStatus, TicketType
from app.models.contact import Contact
from app.models.monitoring_alert import MonitoringAlert
from app.models.organization import Organization
from app.models.ticket import Ticket
from app.models.ticket_schedule import TicketSchedule
from app.schemas.integration_setting import IntegrationSettingUpdate
from app.services import integration_settings, monitoring, schedules


# --- next-run arithmetic ------------------------------------------------


def _schedule(cadence, **kwargs) -> TicketSchedule:
    return TicketSchedule(name="s", subject="s", cadence=cadence, next_run_on=date.today(), **kwargs)


def test_daily_advances_one_day():
    assert schedules.compute_next_run(_schedule(ScheduleCadence.DAILY), date(2026, 8, 1)) == date(2026, 8, 2)


def test_weekly_lands_on_the_requested_weekday():
    # 2026-08-01 is a Saturday; next Monday (0) is the 3rd.
    assert schedules.compute_next_run(_schedule(ScheduleCadence.WEEKLY, day_of_week=0), date(2026, 8, 1)) == date(2026, 8, 3)


def test_weekly_never_returns_the_same_day():
    """Same weekday must jump a full week, not return today - otherwise the
    sweep would fire the schedule again on the very next tick."""
    monday = date(2026, 8, 3)
    assert schedules.compute_next_run(_schedule(ScheduleCadence.WEEKLY, day_of_week=0), monday) == date(2026, 8, 10)


def test_monthly_keeps_the_requested_day():
    got = schedules.compute_next_run(_schedule(ScheduleCadence.MONTHLY, day_of_month=5), date(2026, 8, 6))
    assert got == date(2026, 9, 5)


def test_monthly_day_31_survives_february():
    """A 31st-of-the-month schedule must clamp to the shortest month rather
    than raise - and must not permanently drift to the 28th afterwards."""
    got = schedules.compute_next_run(_schedule(ScheduleCadence.MONTHLY, day_of_month=31), date(2026, 1, 31))
    assert got == date(2026, 2, 28)
    after_february = schedules.compute_next_run(_schedule(ScheduleCadence.MONTHLY, day_of_month=31), got)
    assert after_february == date(2026, 3, 31)


def test_quarterly_advances_three_months():
    got = schedules.compute_next_run(_schedule(ScheduleCadence.QUARTERLY, day_of_month=1), date(2026, 8, 1))
    assert got == date(2026, 11, 1)


# --- the sweep ----------------------------------------------------------


def _make_schedule(db: Session, contact: Contact, **kwargs) -> TicketSchedule:
    fields = {
        "name": "Профилактика",
        "organization_id": contact.organization_id,
        "contact_id": contact.id,
        "subject": "Плановое обслуживание",
        "body": "Проверка бэкапов",
        "type": TicketType.SERVICE_REQUEST,
        "priority": Priority.P3,
        "cadence": ScheduleCadence.MONTHLY,
        "day_of_month": 5,
        "next_run_on": date(2026, 8, 1),
        **kwargs,
    }
    schedule = TicketSchedule(**fields)
    db.add(schedule)
    db.commit()
    return schedule


def test_due_schedule_creates_a_normal_ticket(db: Session, contact: Contact):
    schedule = _make_schedule(db, contact)
    created = schedules.run_due_schedules(db, today=date(2026, 8, 2))
    assert created == 1

    ticket = db.query(Ticket).filter(Ticket.subject == "Плановое обслуживание").order_by(Ticket.id.desc()).first()
    assert ticket is not None
    assert ticket.organization_id == contact.organization_id
    # A scheduled ticket is an ordinary ticket - SLA deadlines and all.
    assert ticket.sla_resolution_due_at is not None

    db.refresh(schedule)
    assert schedule.next_run_on > date(2026, 8, 2)
    assert schedule.last_run_at is not None


def test_schedule_not_yet_due_is_left_alone(db: Session, contact: Contact):
    _make_schedule(db, contact, next_run_on=date(2026, 9, 1))
    assert schedules.run_due_schedules(db, today=date(2026, 8, 2)) == 0


def test_inactive_schedule_does_not_fire(db: Session, contact: Contact):
    _make_schedule(db, contact, is_active=False)
    assert schedules.run_due_schedules(db, today=date(2026, 8, 2)) == 0


def test_overdue_schedule_fires_once_not_once_per_missed_period(db: Session, contact: Contact):
    """If the worker was down for months, the client should get one
    maintenance ticket, not a pile of stale ones."""
    _make_schedule(db, contact, next_run_on=date(2026, 1, 5))
    assert schedules.run_due_schedules(db, today=date(2026, 8, 2)) == 1
    assert schedules.run_due_schedules(db, today=date(2026, 8, 2)) == 0


def test_explicit_engineer_overrides_routing(db: Session, contact: Contact, engineer_user):
    _make_schedule(db, contact, assigned_engineer_id=engineer_user.id)
    schedules.run_due_schedules(db, today=date(2026, 8, 2))
    ticket = db.query(Ticket).filter(Ticket.subject == "Плановое обслуживание").order_by(Ticket.id.desc()).first()
    assert ticket.assigned_engineer_id == engineer_user.id


# --- monitoring ----------------------------------------------------------


@pytest.fixture()
def monitoring_enabled(db: Session):
    integration_settings.upsert(
        db,
        Channel.PORTAL,
        IntegrationSettingUpdate(
            is_enabled=True,
            config={"monitoring": {"auto_resolve": True}},
            secrets={"monitoring_webhook_secret": "s3cret"},
        ),
    )
    return monitoring.load_config(db)


def _alert(event_id="EV-1", status="PROBLEM", **extra) -> dict:
    return {"event_id": event_id, "subject": "Сервис недоступен", "status": status, **extra}


def test_alert_without_id_is_rejected(db: Session, monitoring_enabled):
    with pytest.raises(ValueError):
        monitoring.ingest_alert(db, {"subject": "без id"}, monitoring_enabled)


def test_problem_alert_creates_ticket(db: Session, monitoring_enabled):
    alert = monitoring.ingest_alert(db, _alert(event_id="EV-NEW", host="srv-1", severity="high"), monitoring_enabled)
    assert alert.ticket_id is not None
    ticket = db.get(Ticket, alert.ticket_id)
    assert "srv-1" in ticket.subject  # host is prefixed so the queue is scannable
    assert ticket.priority == Priority.P2  # high -> P2


@pytest.mark.parametrize(
    "severity,expected",
    [("disaster", Priority.P1), ("high", Priority.P2), ("warning", Priority.P3), ("info", Priority.P4), (None, Priority.P3)],
)
def test_severity_maps_to_priority(severity, expected):
    assert monitoring._priority_for(severity) == expected


def test_repeated_problem_does_not_open_a_second_ticket(db: Session, monitoring_enabled):
    """Monitoring flaps; one outage must stay one ticket."""
    first = monitoring.ingest_alert(db, _alert(event_id="EV-FLAP"), monitoring_enabled)
    second = monitoring.ingest_alert(db, _alert(event_id="EV-FLAP"), monitoring_enabled)
    assert first.id == second.id
    assert first.ticket_id == second.ticket_id
    assert db.query(MonitoringAlert).filter(MonitoringAlert.external_id == "EV-FLAP").count() == 1


@pytest.mark.parametrize("recovery_value", ["OK", "resolved", "RECOVERY", "0"])
def test_recovery_values_resolve_the_ticket(db: Session, monitoring_enabled, recovery_value):
    alert = monitoring.ingest_alert(db, _alert(event_id=f"EV-{recovery_value}"), monitoring_enabled)
    monitoring.ingest_alert(db, _alert(event_id=f"EV-{recovery_value}", status=recovery_value), monitoring_enabled)

    ticket = db.get(Ticket, alert.ticket_id)
    assert TicketStatus(ticket.status) == TicketStatus.RESOLVED
    db.refresh(alert)
    assert alert.resolved_at is not None


def test_unknown_status_is_treated_as_a_problem_not_a_recovery(db: Session, monitoring_enabled):
    """A misread recovery would silently close a live incident, so anything
    unrecognized has to mean "still broken"."""
    alert = monitoring.ingest_alert(db, _alert(event_id="EV-WEIRD", status="странный-статус"), monitoring_enabled)
    assert alert.ticket_id is not None
    assert alert.resolved_at is None


def test_auto_resolve_can_be_disabled(db: Session):
    integration_settings.upsert(
        db, Channel.PORTAL,
        IntegrationSettingUpdate(is_enabled=True, config={"monitoring": {"auto_resolve": False}}),
    )
    config = monitoring.load_config(db)
    alert = monitoring.ingest_alert(db, _alert(event_id="EV-NOAUTO"), config)
    monitoring.ingest_alert(db, _alert(event_id="EV-NOAUTO", status="OK"), config)

    ticket = db.get(Ticket, alert.ticket_id)
    assert TicketStatus(ticket.status) != TicketStatus.RESOLVED
    db.refresh(alert)
    assert alert.resolved_at is not None  # the alert closes even if the ticket stays open


def test_recovery_for_unseen_alert_creates_no_ticket(db: Session, monitoring_enabled):
    """"It's fine now" about something we never heard of is pure noise."""
    alert = monitoring.ingest_alert(db, _alert(event_id="EV-GHOST", status="OK"), monitoring_enabled)
    assert alert.ticket_id is None


def test_alert_routes_to_the_named_organization(db: Session, monitoring_enabled, organization: Organization, contact: Contact):
    alert = monitoring.ingest_alert(
        db, _alert(event_id="EV-ORG", organization=organization.name), monitoring_enabled
    )
    assert alert.organization_id == organization.id


def test_alert_with_unknown_organization_still_becomes_a_ticket(db: Session, monitoring_enabled):
    """An alert must never be dropped for want of someone to attribute it to."""
    alert = monitoring.ingest_alert(
        db, _alert(event_id="EV-NOORG", organization="Организации Не Существует"), monitoring_enabled
    )
    assert alert.ticket_id is not None
    ticket = db.get(Ticket, alert.ticket_id)
    assert db.get(Organization, ticket.organization_id).name == "Неизвестные"


def test_disabled_integration_yields_no_config(db: Session):
    integration_settings.upsert(db, Channel.PORTAL, IntegrationSettingUpdate(is_enabled=False))
    assert monitoring.load_config(db) is None


# --- секрет вебхука ------------------------------------------------------


def _request(secret_header: str | None = None, secret_query: str | None = None) -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/webhooks/monitoring",
        "headers": [(b"x-webhook-secret", secret_header.encode())] if secret_header else [],
        "query_string": f"secret={secret_query}".encode() if secret_query else b"",
    }
    return Request(scope)


def test_webhook_secret_accepts_match():
    verify_webhook_secret(_request(secret_header="s3cret"), "s3cret")


def test_webhook_secret_accepts_query_parameter():
    """Не всякая система умеет ставить заголовок — Zabbix проще передаёт
    секрет в URL."""
    verify_webhook_secret(_request(secret_query="s3cret"), "s3cret")


def test_webhook_secret_rejects_mismatch():
    with pytest.raises(HTTPException) as exc:
        verify_webhook_secret(_request(secret_header="wrong"), "s3cret")
    assert exc.value.status_code == 401


def test_webhook_secret_rejects_missing():
    with pytest.raises(HTTPException) as exc:
        verify_webhook_secret(_request(), "s3cret")
    assert exc.value.status_code == 401


def test_unset_secret_lets_everything_through():
    """Секрет не задан — проверять нечего; вебхук остаётся открытым осознанно,
    иначе интеграцию невозможно было бы завести по шагам."""
    verify_webhook_secret(_request(), None)


def test_non_ascii_secret_gives_401_not_500():
    """hmac.compare_digest на не-ASCII строках возбуждает TypeError, и вебхук
    отдавал 500 вместо 401. Поймано живой проверкой интеграции, не тестом.

    Совпасть такой секрет в заголовке всё равно не может (заголовки
    декодируются как latin-1) — поэтому заводить его и запрещено, см.
    test_non_ascii_webhook_secret_is_rejected_on_save. Здесь важно только
    то, что сервер отвечает отказом, а не падает."""
    with pytest.raises(HTTPException) as exc:
        verify_webhook_secret(_request(secret_header="whatever"), "секрет-мониторинга")
    assert exc.value.status_code == 401


def test_non_ascii_webhook_secret_is_rejected_on_save(db: Session):
    """Секрет с кириллицей совпал бы в query-параметре и не совпал бы в
    заголовке — интеграция работала бы через раз. Лучше не дать его завести."""
    with pytest.raises(ValueError):
        integration_settings.upsert(
            db, Channel.PORTAL,
            IntegrationSettingUpdate(secrets={"monitoring_webhook_secret": "секрет-мониторинга"}),
        )

    # Пароль почты не проверяется: он никуда не идёт HTTP-заголовком,
    # и запрещать в нём не-ASCII было бы произволом.
    integration_settings.upsert(
        db, Channel.EMAIL, IntegrationSettingUpdate(secrets={"imap_password": "пароль-почты"})
    )


def test_alerts_endpoint_serialises_dates(db: Session, monitoring_enabled):
    """Схема ответа объявляла created_at/resolved_at строками, и список
    алертов отдавал 500 при любом непустом результате. Тесты дёргали сервис
    напрямую и этого не видели — поэтому здесь проверяется именно эндпоинт."""
    from app.api.routers.monitoring import MonitoringAlertRead, list_alerts

    monitoring.ingest_alert(db, _alert(event_id="EV-SER", host="srv-9"), monitoring_enabled)
    monitoring.ingest_alert(db, _alert(event_id="EV-SER", status="OK"), monitoring_enabled)

    alerts = list_alerts(response=Response(), db=db, _=None)
    rendered = [MonitoringAlertRead.model_validate(a) for a in alerts]

    ours = next(r for r in rendered if r.external_id == "EV-SER")
    assert isinstance(ours.created_at, datetime)
    assert isinstance(ours.resolved_at, datetime)


# --- настройки мониторинга ----------------------------------------------


def test_settings_expose_defaults_before_anything_is_configured(db: Session):
    from app.api.routers.monitoring import get_monitoring_settings

    # Явно приводим настройки к «ничего не настроено»: тесты идут по общей
    # dev-базе, где мониторинг мог быть уже сконфигурирован руками.
    integration_settings.upsert(db, Channel.PORTAL, IntegrationSettingUpdate(config={}))

    settings = get_monitoring_settings(db=db, _=None)

    # Форма должна показывать реальные умолчания, а не пустые поля: иначе
    # администратор решит, что маппинг надо заполнять с нуля.
    assert settings.field_map == monitoring.DEFAULT_FIELD_MAP
    assert settings.auto_resolve is True


def test_saving_settings_keeps_the_secret_when_it_is_not_touched(db: Session, monitoring_enabled):
    from app.api.routers.monitoring import MonitoringSettingsUpdate, update_monitoring_settings

    # Ключ webhook_secret вообще не передаётся — это «не менять».
    result = update_monitoring_settings(MonitoringSettingsUpdate(auto_resolve=False), db=db, _=None)

    assert result.webhook_secret_set is True
    assert result.auto_resolve is False
    # И секрет по-прежнему тот же, а не затёрт пустым значением.
    assert monitoring.load_config(db).webhook_secret == "s3cret"


def test_explicit_null_clears_the_secret(db: Session, monitoring_enabled):
    from app.api.routers.monitoring import MonitoringSettingsUpdate, update_monitoring_settings

    result = update_monitoring_settings(MonitoringSettingsUpdate(webhook_secret=None), db=db, _=None)

    assert result.webhook_secret_set is False
    assert monitoring.load_config(db).webhook_secret is None


def test_field_map_stores_only_the_differences(db: Session, monitoring_enabled):
    """В конфиг пишутся только отличия от умолчаний: если сохранять карту
    целиком, изменение умолчаний в коде не дойдёт до уже настроенных
    установок — они навсегда останутся со старыми именами полей."""
    from app.api.routers.monitoring import MonitoringSettingsUpdate, update_monitoring_settings

    result = update_monitoring_settings(
        MonitoringSettingsUpdate(field_map={**monitoring.DEFAULT_FIELD_MAP, "external_id": "eventid"}),
        db=db, _=None,
    )

    setting = integration_settings.get(db, Channel.PORTAL)
    assert setting.config["monitoring"]["field_map"] == {"external_id": "eventid"}
    # Наружу при этом отдаётся полная карта — форме нужны все поля.
    assert result.field_map["external_id"] == "eventid"
    assert result.field_map["subject"] == "subject"


def test_settings_reject_non_ascii_secret_with_a_readable_message(db: Session, monitoring_enabled):
    from fastapi import HTTPException as FastAPIHTTPException

    from app.api.routers.monitoring import MonitoringSettingsUpdate, update_monitoring_settings

    with pytest.raises(FastAPIHTTPException) as exc:
        update_monitoring_settings(MonitoringSettingsUpdate(webhook_secret="секрет"), db=db, _=None)

    assert exc.value.status_code == 400
    assert "латинских" in exc.value.detail


def test_settings_never_return_the_secret_itself(db: Session, monitoring_enabled):
    from app.api.routers.monitoring import get_monitoring_settings

    settings = get_monitoring_settings(db=db, _=None)

    assert "s3cret" not in settings.model_dump_json()
