from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db import get_db
from app.models.user import User
from app.services import report_export, report_pdf, reports

router = APIRouter(prefix="/reports", tags=["reports"])

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _period(date_from: date | None, date_to: date | None) -> tuple[date, date]:
    today = date.today()
    resolved_to = date_to or today
    return date_from or resolved_to.replace(day=1), resolved_to


def _xlsx(content: bytes, filename: str) -> Response:
    return Response(
        content=content,
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/overview")
def get_overview(
    date_from: date | None = None,
    date_to: date | None = None,
    organization_id: int | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    """Combined report payload (section 9, expanded): SLA compliance, ticket
    flow, engineer workload, CSAT, backlog aging. Defaults to the current
    calendar month when no period is given."""
    date_from, date_to = _period(date_from, date_to)
    return reports.get_overview(db, date_from, date_to, organization_id)


@router.get("/overview.xlsx")
def export_overview(
    date_from: date | None = None,
    date_to: date | None = None,
    organization_id: int | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> Response:
    date_from, date_to = _period(date_from, date_to)
    data = reports.get_overview(db, date_from, date_to, organization_id)
    return _xlsx(
        report_export.overview_workbook(data), report_export.filename_for("otchet", date_from, date_to)
    )


@router.get("/client")
def get_client_report(
    organization_id: int,
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    """Section 9.2: the per-period statement for one client organization."""
    date_from, date_to = _period(date_from, date_to)
    try:
        return reports.get_client_report(db, organization_id, date_from, date_to)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get("/client.xlsx")
def export_client_report(
    organization_id: int,
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> Response:
    date_from, date_to = _period(date_from, date_to)
    try:
        data = reports.get_client_report(db, organization_id, date_from, date_to)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return _xlsx(
        report_export.client_report_workbook(data),
        report_export.filename_for("otchet-klientu", date_from, date_to),
    )


@router.get("/client.pdf")
def export_client_report_pdf(
    organization_id: int,
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> Response:
    """PDF of the client statement (ТЗ р. 9). Only this report is offered as
    PDF - it's the one that leaves the company, where a fixed layout matters.
    The internal overview stays XLSX, since it's meant to be reworked."""
    date_from, date_to = _period(date_from, date_to)
    try:
        data = reports.get_client_report(db, organization_id, date_from, date_to)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    try:
        content = report_pdf.client_report_pdf(data)
    except report_pdf.FontUnavailable as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    filename = report_export.filename_for("otchet-klientu", date_from, date_to).replace(".xlsx", ".pdf")
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
