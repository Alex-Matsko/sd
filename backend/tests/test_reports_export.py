"""Client report and XLSX export (ТЗ р. 9, п. 9.2) - the half of the
reporting requirement that was specified but never built."""

from datetime import date, timedelta
from io import BytesIO

import pytest
from openpyxl import load_workbook
from sqlalchemy.orm import Session

from app.core.enums import Channel, Priority, TicketStatus, TicketType
from app.models.contact import Contact
from app.models.organization import Organization
from app.schemas.ticket import TicketCreate
from app.schemas.time_entry import TimeEntryCreate
from app.services import report_export, reports
from app.services import tickets as tickets_service
from app.services import time_entries as time_entries_service


def _ticket(db: Session, contact: Contact, subject="Отчётная заявка"):
    return tickets_service.create_ticket(
        db,
        TicketCreate(
            contact_id=contact.id, type=TicketType.INCIDENT, channel=Channel.EMAIL, subject=subject,
            manual_priority=Priority.P3, manual_priority_reason="test",
        ),
        actor=None,
    )


def test_client_report_counts_only_that_organization(db: Session, contact: Contact, organization: Organization):
    other_org = Organization(name="Чужая организация")
    db.add(other_org)
    db.flush()
    other_contact = Contact(organization_id=other_org.id, full_name="Чужой контакт")
    db.add(other_contact)
    db.flush()

    _ticket(db, contact, "Наша заявка")
    _ticket(db, other_contact, "Чужая заявка")

    today = date.today()
    report = reports.get_client_report(db, organization.id, today, today)
    subjects = [t["subject"] for t in report["tickets"]]
    assert "Наша заявка" in subjects
    assert "Чужая заявка" not in subjects
    assert report["organization"] == organization.name


def test_client_report_sums_logged_hours(db: Session, contact: Contact, organization: Organization, engineer_user):
    ticket = _ticket(db, contact)
    today = date.today()
    time_entries_service.create_time_entry(
        db, ticket, TimeEntryCreate(entry_date=today, duration_minutes=90, comment=None), engineer_user
    )

    report = reports.get_client_report(db, organization.id, today, today)
    assert report["totals"]["hours"] == 1.5
    row = next(t for t in report["tickets"] if t["display_number"] == ticket.display_number)
    assert row["hours"] == 1.5


def test_client_report_excludes_time_logged_outside_the_period(db: Session, contact: Contact, organization: Organization, engineer_user):
    """Time is attributed to the day it was spent, not to the ticket's dates -
    that's how the hour package is billed."""
    ticket = _ticket(db, contact)
    today = date.today()
    time_entries_service.create_time_entry(
        db, ticket, TimeEntryCreate(entry_date=today - timedelta(days=40), duration_minutes=120, comment=None), engineer_user
    )

    report = reports.get_client_report(db, organization.id, today, today)
    assert report["totals"]["hours"] == 0.0


def test_client_report_without_contract_says_so_instead_of_showing_zeros(db: Session, contact: Contact, organization: Organization):
    """Zeros would read as "your package is exhausted"; the organization
    simply has no package (docs/decisions.md on the default tariff)."""
    _ticket(db, contact)
    today = date.today()
    report = reports.get_client_report(db, organization.id, today, today)
    assert report["package"]["package_total_hours"] == "нет договора"


def test_client_report_reports_package_when_contract_is_active(
    db: Session, contact: Contact, organization: Organization, active_contract, engineer_user
):
    ticket = _ticket(db, contact)
    today = date.today()
    time_entries_service.create_time_entry(
        db, ticket, TimeEntryCreate(entry_date=today, duration_minutes=60, comment=None), engineer_user
    )
    report = reports.get_client_report(db, organization.id, today, today)
    assert isinstance(report["package"]["package_total_hours"], (int, float))
    assert report["package"]["package_used_hours"] >= 1.0


def test_unknown_organization_raises(db: Session):
    with pytest.raises(ValueError):
        reports.get_client_report(db, 10**9, date.today(), date.today())


# --- XLSX rendering -------------------------------------------------


def test_client_report_workbook_has_both_sheets(db: Session, contact: Contact, organization: Organization):
    _ticket(db, contact, "Заявка для выгрузки")
    today = date.today()
    data = reports.get_client_report(db, organization.id, today, today)

    wb = load_workbook(BytesIO(report_export.client_report_workbook(data)))
    assert wb.sheetnames == ["Сводка", "Заявки"]
    summary = {row[0]: row[1] for row in wb["Сводка"].iter_rows(values_only=True)}
    assert summary["Организация"] == organization.name
    assert [c.value for c in wb["Заявки"][1]][0] == "Заявка"


def test_overview_workbook_covers_every_section(db: Session):
    today = date.today()
    data = reports.get_overview(db, today, today)
    wb = load_workbook(BytesIO(report_export.overview_workbook(data)))
    for expected in ("SLA", "Загрузка инженеров", "CSAT", "Возраст backlog"):
        assert expected in wb.sheetnames


def test_sheet_titles_stay_within_excel_limit():
    """Excel rejects sheet names longer than 31 characters - truncation has to
    happen on our side or the file simply fails to open."""
    from openpyxl import Workbook

    wb = Workbook()
    sheet = report_export._write_sheet(wb, "Очень длинное название листа которое точно не влезет", ["A"], [], first=True)
    assert len(sheet.title) <= 31


def test_filename_includes_the_period():
    name = report_export.filename_for("otchet", date(2026, 7, 1), date(2026, 7, 31))
    assert name == "otchet_2026-07-01_2026-07-31.xlsx"
