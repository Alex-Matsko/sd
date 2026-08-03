"""Сформированные отчёты клиентам (ТЗ 9.2).

Отдельно от /reports: там отчёты считаются на лету по любому периоду, здесь
— готовые документы, зафиксированные снимком. Разница существенная для
пользователя: то, что уже сформировано, можно отдать клиенту и быть
уверенным, что цифры не поедут.
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_manager_or_above
from app.db import get_db
from app.models.client_report import ClientReport
from app.models.organization import Organization
from app.models.user import User
from app.services import client_reports as service
from app.services import report_export, report_pdf

router = APIRouter(prefix="/client-reports", tags=["client-reports"])

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class ClientReportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: int
    organization_name: str
    period_start: date
    period_end: date
    period_title: str
    tickets_count: int
    hours: float
    source: str
    generated_at: str
    generated_by: str | None
    sent_at: str | None


class GenerateRequest(BaseModel):
    organization_id: int
    period_start: date
    period_end: date


def _to_read(db: Session, report: ClientReport) -> ClientReportRead:
    organization = db.get(Organization, report.organization_id)
    author = db.get(User, report.generated_by_user_id) if report.generated_by_user_id else None
    return ClientReportRead(
        id=report.id,
        organization_id=report.organization_id,
        # Название берётся из снимка: организацию могли переименовать после
        # того, как отчёт ушёл клиенту, и в списке должно стоять то имя,
        # под которым документ был отправлен.
        organization_name=(report.data or {}).get("organization")
        or (organization.name if organization else "—"),
        period_start=report.period_start,
        period_end=report.period_end,
        period_title=service.period_title(report.period_start, report.period_end),
        tickets_count=report.tickets_count,
        hours=((report.data or {}).get("totals") or {}).get("hours", 0),
        source=report.source,
        generated_at=report.generated_at.isoformat(),
        generated_by=author.full_name if author else None,
        sent_at=report.sent_at.isoformat() if report.sent_at else None,
    )


def _get_or_404(db: Session, report_id: int) -> ClientReport:
    report = db.get(ClientReport, report_id)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Отчёт не найден")
    return report


@router.get("", response_model=list[ClientReportRead])
def list_client_reports(
    response: Response,
    organization_id: int | None = None,
    limit: int = 25,
    offset: int = 0,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[ClientReportRead]:
    query = db.query(ClientReport)
    if organization_id is not None:
        query = query.filter(ClientReport.organization_id == organization_id)
    response.headers["X-Total-Count"] = str(query.count())
    reports = (
        query.order_by(ClientReport.period_start.desc(), ClientReport.id.desc())
        .limit(max(1, min(limit, 200)))
        .offset(max(0, offset))
        .all()
    )
    return [_to_read(db, r) for r in reports]


@router.post("", response_model=ClientReportRead, status_code=status.HTTP_201_CREATED)
def generate_client_report(
    payload: GenerateRequest,
    db: Session = Depends(get_db),
    actor: User = Depends(require_manager_or_above),
) -> ClientReportRead:
    """Формирует отчёт за период и сохраняет снимок. Повторный вызов за тот
    же период перезаписывает снимок и снимает отметку об отправке."""
    if payload.period_end < payload.period_start:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Конец периода раньше начала")
    try:
        report = service.generate(
            db, payload.organization_id, payload.period_start, payload.period_end, actor=actor
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _to_read(db, report)


@router.get("/{report_id}")
def get_client_report(
    report_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> dict:
    """Содержимое снимка — то, что увидит клиент."""
    report = _get_or_404(db, report_id)
    return {**_to_read(db, report).model_dump(), "data": report.data}


class SentUpdate(BaseModel):
    sent: bool = True


@router.post("/{report_id}/sent", response_model=ClientReportRead)
def set_client_report_sent(
    report_id: int,
    payload: SentUpdate | None = None,
    db: Session = Depends(get_db),
    actor: User = Depends(require_manager_or_above),
) -> ClientReportRead:
    """Отметка об отправке ставится и снимается руками: рассылки нет, но без
    отметки невозможно понять, кому отчёт уже ушёл, а кому нет."""
    report = service.set_sent(db, _get_or_404(db, report_id), actor, (payload or SentUpdate()).sent)
    return _to_read(db, report)


def _filename(report: ClientReport, extension: str) -> str:
    return f"otchet-{report.organization_id}-{report.period_start:%Y-%m}.{extension}"


@router.get("/{report_id}/pdf")
def download_client_report_pdf(
    report_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> Response:
    report = _get_or_404(db, report_id)
    try:
        content = report_pdf.client_report_pdf(report.data)
    except report_pdf.FontUnavailable as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{_filename(report, "pdf")}"'},
    )


@router.get("/{report_id}/xlsx")
def download_client_report_xlsx(
    report_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> Response:
    report = _get_or_404(db, report_id)
    return Response(
        content=report_export.client_report_workbook(report.data),
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{_filename(report, "xlsx")}"'},
    )
