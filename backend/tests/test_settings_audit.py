"""Журнал изменений настроек (ТЗ р. 10).

ТЗ требует «audit log всех изменений заявок **и настроек**». Заявки писались,
настройки — нет: по журналу нельзя было установить, кто ослабил SLA перед
отчётным периодом или подменил токен бота. Проверяется, что запись делается
автоматически, с автором, и что секреты в неё не утекают.
"""

from datetime import date

import pytest
from sqlalchemy.orm import Session

from app.core.enums import Channel, ContractStatus, Priority, UserRole
from app.core.security import hash_password
from app.models.audit import AuditLog
from app.models.contract import Contract
from app.models.organization import Organization
from app.models.priority import ImpactUrgencyRule
from app.models.tariff import Tariff, TariffSlaRule
from app.models.user import User
from app.schemas.integration_setting import IntegrationSettingUpdate
from app.services import integration_settings, settings_audit


def _entries(db: Session, entity_type: str) -> list[AuditLog]:
    return (
        db.query(AuditLog)
        .filter(AuditLog.entity_type == entity_type)
        .order_by(AuditLog.id.desc())
        .all()
    )


@pytest.fixture()
def actor(db: Session) -> User:
    user = User(
        full_name="Руководитель Аудит", email="audit-manager@test.local",
        password_hash=hash_password("test1234"), role=UserRole.MANAGER,
    )
    db.add(user)
    db.commit()
    settings_audit.set_actor(db, user.id)
    return user


def test_sla_rule_change_is_recorded_with_the_author(db: Session, default_tariff: Tariff, actor: User):
    """Самое важное для ITSM: по журналу должно быть видно, кто и когда
    поменял обязательства по SLA."""
    rule = (
        db.query(TariffSlaRule)
        .filter(TariffSlaRule.tariff_id == default_tariff.id, TariffSlaRule.priority == Priority.P1)
        .first()
    )
    assert rule is not None, "выполните `python -m app.seed` перед тестами"
    was = rule.resolution_time_minutes

    rule.resolution_time_minutes = was + 120
    db.add(rule)
    db.commit()

    entry = _entries(db, "tariff_sla_rules")[0]
    assert entry.action == "updated"
    assert entry.user_id == actor.id
    assert entry.changes["resolution_time_minutes"] == {"from": was, "to": was + 120}


def test_priority_matrix_change_is_recorded(db: Session, actor: User):
    rule = db.query(ImpactUrgencyRule).first()
    assert rule is not None
    rule.priority = Priority.P1 if rule.priority != Priority.P1 else Priority.P2
    db.add(rule)
    db.commit()

    assert _entries(db, "priority_matrix")[0].user_id == actor.id


def test_contract_change_is_recorded(db: Session, organization: Organization, default_tariff: Tariff, actor: User):
    contract = Contract(
        organization_id=organization.id, number="AUDIT-1", start_date=date(2026, 1, 1),
        tariff_id=default_tariff.id, included_hours_per_month=10,
        overage_rate_per_hour=1500, status=ContractStatus.ACTIVE,
    )
    db.add(contract)
    db.commit()

    created = _entries(db, "contract")[0]
    assert created.action == "created"

    contract.included_hours_per_month = 20
    db.add(contract)
    db.commit()

    updated = _entries(db, "contract")[0]
    assert updated.action == "updated"
    assert updated.changes["included_hours_per_month"]["to"] == 20


def test_role_change_is_recorded(db: Session, actor: User):
    target = User(
        full_name="Сотрудник Роль", email="audit-role@test.local",
        password_hash=hash_password("test1234"), role=UserRole.ENGINEER,
    )
    db.add(target)
    db.commit()

    target.role = UserRole.MANAGER
    db.add(target)
    db.commit()

    entry = _entries(db, "user")[0]
    assert entry.action == "updated"
    assert entry.changes["role"] == {"from": "engineer", "to": "manager"}


def test_secrets_never_reach_the_journal(db: Session, actor: User):
    """Токен бота не должен осесть в аудите открытым текстом: журнал читают
    шире, чем настройки каналов."""
    secret = "s3cret-bot-token-should-not-appear"
    integration_settings.upsert(
        db, Channel.TELEGRAM, IntegrationSettingUpdate(is_enabled=True, secrets={"bot_token": secret})
    )

    entry = _entries(db, "integration_setting")[0]
    assert secret not in str(entry.changes)
    assert entry.changes["secrets_encrypted"] == "изменено"


def test_password_hash_is_not_journalled(db: Session, actor: User):
    target = User(
        full_name="Сотрудник Пароль", email="audit-pass@test.local",
        password_hash=hash_password("test1234"), role=UserRole.ENGINEER,
    )
    db.add(target)
    db.commit()

    target.password_hash = hash_password("another-password")
    db.add(target)
    db.commit()

    entry = _entries(db, "user")[0]
    assert entry.changes["password_hash"] == "изменено"


def test_tickets_are_not_double_journalled(db: Session, contact, actor: User):
    """У заявок свои осмысленные записи («статус изменён»); слушатель не
    должен дублировать их набором полей."""
    from app.core.enums import TicketType
    from app.schemas.ticket import TicketCreate
    from app.services import tickets as tickets_service

    before = db.query(AuditLog).filter(AuditLog.entity_type == "ticket").count()
    tickets_service.create_ticket(
        db,
        TicketCreate(
            contact_id=contact.id, type=TicketType.INCIDENT, channel=Channel.EMAIL,
            subject="Заявка для аудита", manual_priority=Priority.P3, manual_priority_reason="test",
        ),
        actor=None,
    )
    after = db.query(AuditLog).filter(AuditLog.entity_type == "ticket").count()
    assert after == before + 1
