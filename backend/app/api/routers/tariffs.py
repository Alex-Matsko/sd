from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_manager_or_above
from app.db import get_db
from app.models.tariff import Tariff, TariffSlaRule
from app.models.user import User
from app.schemas.tariff import TariffCreate, TariffRead, TariffSlaRuleCreate, TariffUpdate

router = APIRouter(prefix="/tariffs", tags=["tariffs"])


@router.get("", response_model=list[TariffRead])
def list_tariffs(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> list[Tariff]:
    return db.query(Tariff).order_by(Tariff.name).all()


@router.post("", response_model=TariffRead, status_code=status.HTTP_201_CREATED)
def create_tariff(
    payload: TariffCreate, db: Session = Depends(get_db), _: User = Depends(require_manager_or_above)
) -> Tariff:
    if db.query(Tariff).filter(Tariff.code == payload.code).first() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Тариф с таким кодом уже существует")
    tariff = Tariff(
        code=payload.code,
        name=payload.name,
        description=payload.description,
        business_calendar_id=payload.business_calendar_id,
    )
    db.add(tariff)
    db.flush()
    for rule in payload.sla_rules:
        db.add(TariffSlaRule(tariff_id=tariff.id, **rule.model_dump()))
    db.commit()
    db.refresh(tariff)
    return tariff


@router.get("/{tariff_id}", response_model=TariffRead)
def get_tariff(tariff_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> Tariff:
    tariff = db.get(Tariff, tariff_id)
    if tariff is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Тариф не найден")
    return tariff


@router.patch("/{tariff_id}", response_model=TariffRead)
def update_tariff(
    tariff_id: int,
    payload: TariffUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_manager_or_above),
) -> Tariff:
    tariff = db.get(Tariff, tariff_id)
    if tariff is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Тариф не найден")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(tariff, field, value)
    db.add(tariff)
    db.commit()
    db.refresh(tariff)
    return tariff


@router.put("/{tariff_id}/sla-rules", response_model=TariffRead)
def replace_sla_rules(
    tariff_id: int,
    rules: list[TariffSlaRuleCreate],
    db: Session = Depends(get_db),
    _: User = Depends(require_manager_or_above),
) -> Tariff:
    tariff = db.get(Tariff, tariff_id)
    if tariff is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Тариф не найден")
    db.query(TariffSlaRule).filter(TariffSlaRule.tariff_id == tariff_id).delete()
    for rule in rules:
        db.add(TariffSlaRule(tariff_id=tariff_id, **rule.model_dump()))
    db.commit()
    db.refresh(tariff)
    return tariff
