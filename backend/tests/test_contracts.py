from datetime import date

from app.core.enums import ContractStatus
from app.models.contract import Contract
from app.services.contracts import resolve_contract_and_tariff


def test_resolve_uses_active_contract(db, organization, active_contract):
    contract, tariff, has_no_active_contract = resolve_contract_and_tariff(db, organization.id)
    assert contract.id == active_contract.id
    assert tariff.id == active_contract.tariff_id
    assert has_no_active_contract is False


def test_resolve_falls_back_to_default_tariff_without_contract(db, organization, default_tariff):
    """docs/decisions.md: "SLA/договор при отсутствии активного договора" -
    ticket creation must not be blocked, it just falls back to the default
    tariff and is flagged for the dispatcher."""
    contract, tariff, has_no_active_contract = resolve_contract_and_tariff(db, organization.id)
    assert contract is None
    assert tariff.id == default_tariff.id
    assert has_no_active_contract is True


def test_expired_contract_is_not_used(db, organization, default_tariff):
    expired = Contract(
        organization_id=organization.id,
        number="EXPIRED-1",
        start_date=date(2020, 1, 1),
        end_date=date(2020, 12, 31),
        tariff_id=default_tariff.id,
        included_hours_per_month=10,
        overage_rate_per_hour=1000,
        status=ContractStatus.ACTIVE,
    )
    db.add(expired)
    db.commit()

    contract, _tariff, has_no_active_contract = resolve_contract_and_tariff(db, organization.id)
    assert contract is None
    assert has_no_active_contract is True


def test_suspended_contract_is_not_used(db, organization, active_contract):
    active_contract.status = ContractStatus.SUSPENDED
    db.add(active_contract)
    db.commit()

    contract, _tariff, has_no_active_contract = resolve_contract_and_tariff(db, organization.id)
    assert contract is None
    assert has_no_active_contract is True
