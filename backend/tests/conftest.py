from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.core.enums import ContractStatus, UserRole
from app.core.security import hash_password
from app.models.contact import Contact
from app.models.contract import Contract
from app.models.organization import Organization
from app.models.tariff import Tariff
from app.models.user import User

engine = create_engine(settings.database_url, future=True)


@pytest.fixture()
def db():
    """Each test runs inside a savepoint on top of the already-seeded dev
    database (run `alembic upgrade head && python -m app.seed` first, same as
    the app container does on boot) and is rolled back at teardown - including
    changes made via nested `session.commit()` calls in the service layer,
    since the session joins the outer transaction as a savepoint."""
    connection = engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection, join_transaction_mode="create_savepoint")()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture()
def default_tariff(db: Session) -> Tariff:
    tariff = db.query(Tariff).filter(Tariff.code == settings.default_tariff_code).first()
    assert tariff is not None, "run `python -m app.seed` against the test database before running tests"
    return tariff


@pytest.fixture()
def organization(db: Session) -> Organization:
    org = Organization(name="Тестовая организация")
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


@pytest.fixture()
def contact(db: Session, organization: Organization) -> Contact:
    c = Contact(organization_id=organization.id, full_name="Иван Тестов")
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


@pytest.fixture()
def active_contract(db: Session, organization: Organization, default_tariff: Tariff) -> Contract:
    contract = Contract(
        organization_id=organization.id,
        number="TEST-1",
        start_date=date(2026, 1, 1),
        end_date=None,
        tariff_id=default_tariff.id,
        included_hours_per_month=10,
        overage_rate_per_hour=1500,
        status=ContractStatus.ACTIVE,
    )
    db.add(contract)
    db.commit()
    db.refresh(contract)
    return contract


@pytest.fixture()
def engineer_user(db: Session) -> User:
    user = User(
        full_name="Инженер Тестов",
        email="engineer.test@o-horizons.com",
        password_hash=hash_password("test123"),
        role=UserRole.ENGINEER,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
