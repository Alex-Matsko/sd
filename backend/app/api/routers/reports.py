from datetime import date

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db import get_db
from app.models.user import User
from app.services import report_export, reports

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


# Отчёт клиенту «на лету» отсюда убран. Он жил в двух местах: здесь считался
# по запросу, а в /client-reports сохраняется снимком. Два пути к одному
# документу — это две разные версии цифр за один и тот же месяц, причём
# несохранённая никак не отличима от отправленной клиенту. Осталась одна
# дорога: сформировать отчёт (он же снимок) и скачать его из раздела
# «Отчёты клиентам». См. docs/decisions.md.
