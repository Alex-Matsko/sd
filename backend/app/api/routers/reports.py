from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db import get_db
from app.models.user import User
from app.services import reports

router = APIRouter(prefix="/reports", tags=["reports"])


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
    today = date.today()
    date_to = date_to or today
    date_from = date_from or today.replace(day=1)
    return reports.get_overview(db, date_from, date_to, organization_id)
