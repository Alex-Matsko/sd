from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.audit import AuditLog
from app.models.message import Message
from app.models.time_entry import TimeEntry


def get_ticket_history(db: Session, ticket_id: int) -> list[AuditLog]:
    message_ids = select(Message.id).where(Message.ticket_id == ticket_id)
    time_entry_ids = select(TimeEntry.id).where(TimeEntry.ticket_id == ticket_id)
    stmt = (
        select(AuditLog)
        .where(
            or_(
                (AuditLog.entity_type == "ticket") & (AuditLog.entity_id == ticket_id),
                (AuditLog.entity_type == "message") & AuditLog.entity_id.in_(message_ids),
                (AuditLog.entity_type == "time_entry") & AuditLog.entity_id.in_(time_entry_ids),
            )
        )
        .order_by(AuditLog.created_at.asc())
    )
    return list(db.scalars(stmt))


def record(
    db: Session,
    *,
    entity_type: str,
    entity_id: int,
    action: str,
    user_id: int | None,
    changes: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            user_id=user_id,
            changes=changes,
        )
    )
