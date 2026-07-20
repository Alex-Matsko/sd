from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_dispatcher_or_above
from app.db import get_db
from app.models.organization import Organization, OrganizationEmailDomain
from app.models.user import User
from app.schemas.organization import OrganizationCreate, OrganizationRead, OrganizationUpdate
from app.services import billing
from app.services.contracts import get_active_contract

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.get("", response_model=list[OrganizationRead])
def list_organizations(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> list[Organization]:
    return db.query(Organization).order_by(Organization.name).all()


@router.post("", response_model=OrganizationRead, status_code=status.HTTP_201_CREATED)
def create_organization(
    payload: OrganizationCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_dispatcher_or_above),
) -> Organization:
    org = Organization(
        name=payload.name,
        legal_name=payload.legal_name,
        status=payload.status,
        account_manager_id=payload.account_manager_id,
    )
    db.add(org)
    db.flush()
    for domain in payload.email_domains:
        db.add(OrganizationEmailDomain(organization_id=org.id, domain=domain.lower()))
    db.commit()
    db.refresh(org)
    return org


@router.get("/{organization_id}", response_model=OrganizationRead)
def get_organization(
    organization_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> Organization:
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Организация не найдена")
    return org


@router.patch("/{organization_id}", response_model=OrganizationRead)
def update_organization(
    organization_id: int,
    payload: OrganizationUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_dispatcher_or_above),
) -> Organization:
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Организация не найдена")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(org, field, value)
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


@router.get("/{organization_id}/usage")
def get_organization_usage(
    organization_id: int,
    year: int = Query(default_factory=lambda: date.today().year),
    month: int = Query(default_factory=lambda: date.today().month),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    """Real-time package usage for the org's active contract (section 5)."""
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Организация не найдена")
    contract = get_active_contract(db, organization_id)
    if contract is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="У организации нет активного договора")
    return billing.get_organization_usage(db, organization_id, contract, year, month)
