from datetime import date

from sqlalchemy.orm import Session

from app.config import settings
from app.core.enums import ContractStatus
from app.models.contract import Contract
from app.models.tariff import Tariff


def get_active_contract(db: Session, organization_id: int, on_date: date | None = None) -> Contract | None:
    on_date = on_date or date.today()
    return (
        db.query(Contract)
        .filter(
            Contract.organization_id == organization_id,
            Contract.status == ContractStatus.ACTIVE,
            Contract.start_date <= on_date,
            (Contract.end_date.is_(None)) | (Contract.end_date >= on_date),
        )
        .order_by(Contract.start_date.desc())
        .first()
    )


def get_default_tariff(db: Session) -> Tariff:
    tariff = db.query(Tariff).filter(Tariff.code == settings.default_tariff_code).first()
    if tariff is None:
        raise RuntimeError(
            f"Тариф по умолчанию '{settings.default_tariff_code}' не найден - "
            "засейте его при инициализации (см. docs/decisions.md)"
        )
    return tariff


def resolve_contract_and_tariff(db: Session, organization_id: int) -> tuple[Contract | None, Tariff, bool]:
    """Returns (contract_or_none, tariff, has_no_active_contract). If the
    organization has no active contract, the default fallback tariff is used and
    has_no_active_contract=True (docs/decisions.md: "SLA/договор при отсутствии
    активного договора")."""
    contract = get_active_contract(db, organization_id)
    if contract is not None:
        return contract, contract.tariff, False
    return None, get_default_tariff(db), True
