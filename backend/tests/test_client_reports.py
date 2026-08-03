"""Отчёты клиентам за период (ТЗ 9.2): состав, снимок, автоформирование.

Ключевое здесь — что отчёт хранится снимком. Документ, отданный клиенту, не
должен меняться от того, что кто-то дописал списание задним числом; поэтому
проверяется именно неизменность и то, что переформирование — явное действие.
"""

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from app.core.enums import Channel, Priority, TicketStatus, TicketType
from app.models.client_report import ClientReport
from app.models.contact import Contact
from app.models.contract import Contract
from app.models.organization import Organization
from app.models.ticket import Ticket
from app.models.user import User
from app.schemas.ticket import TicketCreate
from app.schemas.time_entry import TimeEntryCreate
from app.services import client_reports, reports
from app.services import tickets as tickets_service
from app.services import time_entries as time_entries_service

PERIOD_START = date(2026, 6, 1)
PERIOD_END = date(2026, 6, 30)


def _ticket(db: Session, contact: Contact, subject: str, created_at: datetime) -> Ticket:
    ticket = tickets_service.create_ticket(
        db,
        TicketCreate(
            contact_id=contact.id, type=TicketType.INCIDENT, channel=Channel.EMAIL, subject=subject,
            manual_priority=Priority.P3, manual_priority_reason="test",
        ),
        actor=None,
    )
    # Заявки создаются «сейчас», а отчёт нужен за конкретный месяц.
    ticket.created_at = created_at
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return ticket


# --- состав отчёта ------------------------------------------------------


def test_report_covers_only_the_requested_organization(db: Session, contact: Contact, organization: Organization):
    other_org = Organization(name="Чужая организация")
    db.add(other_org)
    db.commit()
    other_contact = Contact(organization_id=other_org.id, full_name="Чужой контакт")
    db.add(other_contact)
    db.commit()

    _ticket(db, contact, "Наша заявка", datetime(2026, 6, 10, tzinfo=timezone.utc))
    _ticket(db, other_contact, "Чужая заявка", datetime(2026, 6, 10, tzinfo=timezone.utc))

    data = reports.get_client_report(db, organization.id, PERIOD_START, PERIOD_END)

    subjects = [t["subject"] for t in data["tickets"]]
    assert "Наша заявка" in subjects
    assert "Чужая заявка" not in subjects


def test_report_includes_sla_and_breakdowns(db: Session, contact: Contact, organization: Organization):
    ticket = _ticket(db, contact, "Не работает почта", datetime(2026, 6, 5, tzinfo=timezone.utc))
    ticket.sla_reaction_met = True
    ticket.sla_resolution_met = False
    db.add(ticket)
    db.commit()

    data = reports.get_client_report(db, organization.id, PERIOD_START, PERIOD_END)

    assert data["sla"]["reaction_met_pct"] == 100.0
    assert data["sla"]["resolution_met_pct"] == 0.0
    assert data["sla"]["resolution_missed"] == 1
    assert data["by_channel"] == [{"channel": "Email", "count": 1}]
    assert data["by_category"] == [{"category": "Без категории", "count": 1}]


def test_report_hides_engineer_names(db: Session, contact: Contact, organization: Organization, engineer_user: User):
    """Клиент не должен видеть, кто именно из инженеров с ним работал."""
    ticket = _ticket(db, contact, "Заявка с исполнителем", datetime(2026, 6, 5, tzinfo=timezone.utc))
    ticket.assigned_engineer_id = engineer_user.id
    db.add(ticket)
    db.commit()

    data = reports.get_client_report(db, organization.id, PERIOD_START, PERIOD_END)

    assert engineer_user.full_name not in str(data)


def test_organization_without_contract_gets_a_message_not_zeros(db: Session, contact: Contact, organization: Organization):
    """Нули читались бы как «пакет исчерпан» — а договора просто нет."""
    data = reports.get_client_report(db, organization.id, PERIOD_START, PERIOD_END)
    assert data["package"]["package_total_hours"] == "нет договора"


# --- снимок -------------------------------------------------------------


def test_generated_report_is_a_snapshot(db: Session, contact: Contact, organization: Organization, active_contract: Contract, engineer_user: User):
    ticket = _ticket(db, contact, "Заявка июня", datetime(2026, 6, 15, tzinfo=timezone.utc))
    report = client_reports.generate(db, organization.id, PERIOD_START, PERIOD_END)
    assert report.data["totals"]["hours"] == 0

    # Списание внесено задним числом уже после того, как отчёт сформирован.
    time_entries_service.create_time_entry(
        db, ticket, TimeEntryCreate(entry_date=date(2026, 6, 20), duration_minutes=120), engineer_user
    )
    db.refresh(report)

    # Документ, который уже мог уйти клиенту, меняться не должен.
    assert report.data["totals"]["hours"] == 0

    updated = client_reports.generate(db, organization.id, PERIOD_START, PERIOD_END)
    assert updated.data["totals"]["hours"] == 2


def test_regenerating_clears_the_sent_mark(db: Session, organization: Organization, engineer_user: User):
    report = client_reports.generate(db, organization.id, PERIOD_START, PERIOD_END)
    client_reports.mark_sent(db, report, engineer_user)
    assert report.sent_at is not None

    # У клиента на руках старые цифры — отметка «отправлен» про новый снимок
    # врала бы.
    again = client_reports.generate(db, organization.id, PERIOD_START, PERIOD_END)
    assert again.sent_at is None


def test_regenerating_does_not_create_a_duplicate(db: Session, organization: Organization):
    first = client_reports.generate(db, organization.id, PERIOD_START, PERIOD_END)
    second = client_reports.generate(db, organization.id, PERIOD_START, PERIOD_END)

    assert first.id == second.id
    assert (
        db.query(ClientReport)
        .filter(ClientReport.organization_id == organization.id, ClientReport.period_start == PERIOD_START)
        .count()
        == 1
    )


# --- заголовок периода --------------------------------------------------


@pytest.mark.parametrize(
    "start,end,expected",
    [
        (date(2026, 7, 1), date(2026, 7, 31), "Июль 2026"),
        (date(2026, 2, 1), date(2026, 2, 28), "Февраль 2026"),
        (date(2026, 7, 1), date(2026, 7, 15), "01.07.2026 — 15.07.2026"),
        (date(2026, 7, 5), date(2026, 8, 4), "05.07.2026 — 04.08.2026"),
    ],
)
def test_period_title(start, end, expected):
    """В шапке документа, который читает клиент, «2026-07-01 — 2026-07-31»
    выглядит выгрузкой из базы, а не отчётом за июль."""
    assert client_reports.period_title(start, end) == expected


def test_february_of_a_leap_year_is_still_a_whole_month():
    assert client_reports.period_title(date(2028, 2, 1), date(2028, 2, 29)) == "Февраль 2028"


@pytest.mark.parametrize(
    "today,expected",
    [(date(2026, 8, 3), (2026, 7)), (date(2026, 1, 15), (2025, 12)), (date(2026, 3, 1), (2026, 2))],
)
def test_previous_month(today, expected):
    assert client_reports.previous_month(today) == expected


# --- автоформирование ---------------------------------------------------


def test_monthly_generation_covers_organizations_with_contracts(
    db: Session, organization: Organization, active_contract: Contract
):
    client_reports.generate_monthly_reports(db, today=date(2026, 7, 1))

    report = (
        db.query(ClientReport)
        .filter(ClientReport.organization_id == organization.id, ClientReport.period_start == date(2026, 6, 1))
        .one()
    )
    assert report.source == "auto"
    assert report.period_end == date(2026, 6, 30)
    # Ничего не отправляется: рассылки нет, решает человек.
    assert report.sent_at is None


def test_monthly_generation_is_idempotent(db: Session, organization: Organization, active_contract: Contract):
    """Проход идёт на каждом тике воркера — второй раз он не должен ни
    плодить отчёты, ни перезатирать уже сформированные."""
    client_reports.generate_monthly_reports(db, today=date(2026, 7, 1))
    report = (
        db.query(ClientReport)
        .filter(ClientReport.organization_id == organization.id, ClientReport.period_start == date(2026, 6, 1))
        .one()
    )
    generated_at = report.generated_at

    created = client_reports.generate_monthly_reports(db, today=date(2026, 7, 1))

    db.refresh(report)
    assert created == 0
    assert report.generated_at == generated_at


def test_monthly_generation_does_not_overwrite_a_manual_report(
    db: Session, organization: Organization, active_contract: Contract
):
    """Руководитель мог переформировать отчёт вручную после исправления
    списаний — автопроход не должен затирать его работу."""
    manual = client_reports.generate(db, organization.id, date(2026, 6, 1), date(2026, 6, 30))
    assert manual.source == "manual"

    client_reports.generate_monthly_reports(db, today=date(2026, 7, 1))

    db.refresh(manual)
    assert manual.source == "manual"


def test_one_broken_organization_does_not_stop_the_rest(
    db: Session, organization: Organization, active_contract: Contract, monkeypatch
):
    """Сломанный клиент не должен оставить без отчётов всех остальных."""
    other = Organization(name="Организация с проблемой")
    db.add(other)
    db.commit()
    db.add(
        Contract(
            organization_id=other.id, number="TEST-BROKEN", start_date=date(2026, 1, 1),
            tariff_id=active_contract.tariff_id, included_hours_per_month=5,
            overage_rate_per_hour=1000, status=active_contract.status,
        )
    )
    db.commit()

    original = reports.get_client_report

    def failing(session, organization_id, *args, **kwargs):
        if organization_id == other.id:
            raise RuntimeError("сломалось")
        return original(session, organization_id, *args, **kwargs)

    monkeypatch.setattr(reports, "get_client_report", failing)

    client_reports.generate_monthly_reports(db, today=date(2026, 7, 1))

    assert (
        db.query(ClientReport)
        .filter(ClientReport.organization_id == organization.id, ClientReport.period_start == date(2026, 6, 1))
        .count()
        == 1
    )


# --- PDF ----------------------------------------------------------------


def test_pdf_renders_with_the_russian_period_title(db: Session, contact: Contact, organization: Organization):
    from app.services import report_pdf

    _ticket(db, contact, "Заявка для PDF", datetime(2026, 6, 10, tzinfo=timezone.utc))
    data = reports.get_client_report(db, organization.id, PERIOD_START, PERIOD_END)

    content = report_pdf.client_report_pdf(data)

    assert content.startswith(b"%PDF")
    assert len(content) > 2000
