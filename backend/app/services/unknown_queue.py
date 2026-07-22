"""Shared "Неизвестные" placeholder organization (section 2, rule 4): any
channel that can't match an inbound sender to an existing contact or a
registered organization routes them here for a dispatcher to re-triage,
instead of every channel adapter inventing its own parallel concept. Looked
up by name each time rather than a dedicated flag column - same pattern as
the default tariff's reserved `code` (services/contracts.py)."""

from sqlalchemy.orm import Session

from app.core.enums import OrganizationStatus
from app.models.organization import Organization

UNKNOWN_ORGANIZATION_NAME = "Неизвестные"


def get_or_create_unknown_organization(db: Session) -> Organization:
    org = db.query(Organization).filter(Organization.name == UNKNOWN_ORGANIZATION_NAME).first()
    if org is None:
        org = Organization(name=UNKNOWN_ORGANIZATION_NAME, status=OrganizationStatus.ACTIVE)
        db.add(org)
        db.flush()
    return org
