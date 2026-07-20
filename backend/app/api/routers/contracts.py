from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_manager_or_above
from app.db import get_db
from app.models.contract import Contract
from app.models.user import User
from app.schemas.contract import ContractCreate, ContractRead, ContractUpdate

router = APIRouter(prefix="/contracts", tags=["contracts"])


@router.get("", response_model=list[ContractRead])
def list_contracts(
    organization_id: int | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[Contract]:
    query = db.query(Contract)
    if organization_id is not None:
        query = query.filter(Contract.organization_id == organization_id)
    return query.order_by(Contract.start_date.desc()).all()


@router.post("", response_model=ContractRead, status_code=status.HTTP_201_CREATED)
def create_contract(
    payload: ContractCreate, db: Session = Depends(get_db), _: User = Depends(require_manager_or_above)
) -> Contract:
    contract = Contract(**payload.model_dump())
    db.add(contract)
    db.commit()
    db.refresh(contract)
    return contract


@router.get("/{contract_id}", response_model=ContractRead)
def get_contract(contract_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> Contract:
    contract = db.get(Contract, contract_id)
    if contract is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Договор не найден")
    return contract


@router.patch("/{contract_id}", response_model=ContractRead)
def update_contract(
    contract_id: int,
    payload: ContractUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_manager_or_above),
) -> Contract:
    contract = db.get(Contract, contract_id)
    if contract is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Договор не найден")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(contract, field, value)
    db.add(contract)
    db.commit()
    db.refresh(contract)
    return contract
