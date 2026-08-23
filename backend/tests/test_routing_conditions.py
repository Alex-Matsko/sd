"""Условия в правилах маршрутизации (ТЗ 4.4).

Раньше правило было ровно одним признаком: «организация → инженер» или
«категория → группа». Случай «заявки этого клиента по 1С — второй линии, но
только не аварии» приходилось собирать из нескольких правил и надеяться на
их порядок. Здесь проверяются сочетания условий и то, что заведённые ранее
правила продолжают работать без переделки.
"""

import pytest
from sqlalchemy.orm import Session

from app.core.enums import RoutingRuleType, UserRole
from app.core.security import hash_password
from app.models.category import Category
from app.models.organization import Organization
from app.models.routing import RoutingRule
from app.models.team import Team
from app.models.user import User
from app.services import routing


@pytest.fixture()
def engineer(db: Session) -> User:
    user = User(
        full_name="Инженер Маршрутов", email="routing-engineer@test.local",
        password_hash=hash_password("test1234"), role=UserRole.ENGINEER,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def team(db: Session) -> Team:
    team = Team(name="Вторая линия")
    db.add(team)
    db.commit()
    db.refresh(team)
    return team


def _rule(db: Session, *, conditions, match="all", engineer_id=None, team_id=None, order=1) -> RoutingRule:
    rule = RoutingRule(
        order=order,
        rule_type=RoutingRuleType.ORGANIZATION_TO_ENGINEER,
        is_active=True,
        match=match,
        conditions=conditions,
        target_engineer_id=engineer_id,
        target_team_id=team_id,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


def _facts(db: Session, organization: Organization, **kwargs) -> routing.TicketFacts:
    category_id = kwargs.get("category_id")
    return routing.TicketFacts(
        organization_id=organization.id,
        category_path=routing._category_path(db, category_id),
        **kwargs,
    )


# --- «все условия» ------------------------------------------------------


def test_all_conditions_must_match(db: Session, organization: Organization, engineer: User):
    rule = _rule(
        db,
        conditions=[
            {"field": "organization", "value": organization.id},
            {"field": "priority", "value": "P1"},
        ],
        engineer_id=engineer.id,
    )

    assert routing.rule_matches(rule, _facts(db, organization, priority="P1"))
    assert not routing.rule_matches(rule, _facts(db, organization, priority="P3"))


# --- «любое из условий» -------------------------------------------------


def test_any_condition_is_enough(db: Session, organization: Organization, engineer: User):
    """Дежурному по авариям всё равно, из какого канала пришла заявка."""
    rule = _rule(
        db,
        match="any",
        conditions=[
            {"field": "priority", "value": "P1"},
            {"field": "channel", "value": "phone"},
        ],
        engineer_id=engineer.id,
    )

    assert routing.rule_matches(rule, _facts(db, organization, priority="P1", channel="email"))
    assert routing.rule_matches(rule, _facts(db, organization, priority="P3", channel="phone"))
    assert not routing.rule_matches(rule, _facts(db, organization, priority="P3", channel="email"))


# --- «кроме» ------------------------------------------------------------


def test_negated_condition_excludes(db: Session, organization: Organization, team: Team):
    """«Всё этого клиента, кроме аварий» — аварии ведёт другой человек."""
    rule = _rule(
        db,
        conditions=[
            {"field": "organization", "value": organization.id},
            {"field": "priority", "value": "P1", "negate": True},
        ],
        team_id=team.id,
    )

    assert routing.rule_matches(rule, _facts(db, organization, priority="P3"))
    assert not routing.rule_matches(rule, _facts(db, organization, priority="P1"))


def test_negation_applies_only_to_its_own_condition(db: Session, organization: Organization, team: Team):
    other = Organization(name="Другая организация")
    db.add(other)
    db.commit()

    rule = _rule(
        db,
        conditions=[
            {"field": "organization", "value": organization.id},
            {"field": "channel", "value": "email", "negate": True},
        ],
        team_id=team.id,
    )

    assert routing.rule_matches(rule, _facts(db, organization, channel="phone"))
    # Чужая организация не подходит, даже если канал не почта.
    assert not routing.rule_matches(rule, _facts(db, other, channel="phone"))


# --- список значений ----------------------------------------------------


def test_list_of_values_reads_as_any_of(db: Session, organization: Organization, engineer: User):
    """«Канал — Telegram или MAX» должно быть одним условием, а не двумя
    правилами."""
    rule = _rule(
        db,
        conditions=[{"field": "channel", "value": ["telegram", "max"]}],
        engineer_id=engineer.id,
    )

    assert routing.rule_matches(rule, _facts(db, organization, channel="telegram"))
    assert routing.rule_matches(rule, _facts(db, organization, channel="max"))
    assert not routing.rule_matches(rule, _facts(db, organization, channel="email"))


# --- категории ----------------------------------------------------------


def test_parent_category_catches_children(db: Session, organization: Organization, team: Team):
    """Правило на «1С» должно ловить заявки в «1С → Обновление
    конфигурации»: иначе правило надо заводить на каждую подкатегорию."""
    parent = Category(name="1С")
    db.add(parent)
    db.commit()
    child = Category(name="Обновление конфигурации", parent_id=parent.id)
    db.add(child)
    db.commit()

    rule = _rule(db, conditions=[{"field": "category", "value": parent.id}], team_id=team.id)

    assert routing.rule_matches(rule, _facts(db, organization, category_id=child.id))


# --- порядок и совместимость -------------------------------------------


def test_first_matching_rule_wins(db: Session, organization: Organization, engineer: User, team: Team):
    _rule(db, order=1, conditions=[{"field": "priority", "value": "P1"}], engineer_id=engineer.id)
    _rule(db, order=2, conditions=[{"field": "organization", "value": organization.id}], team_id=team.id)

    team_id, engineer_id = routing.resolve_assignment(db, organization.id, None, priority="P1")
    assert engineer_id == engineer.id and team_id is None

    team_id, engineer_id = routing.resolve_assignment(db, organization.id, None, priority="P3")
    assert team_id == team.id and engineer_id is None


def test_old_rules_without_conditions_still_work(db: Session, organization: Organization, engineer: User):
    """Правила, заведённые до появления условий, переделывать не нужно."""
    rule = RoutingRule(
        order=1,
        rule_type=RoutingRuleType.ORGANIZATION_TO_ENGINEER,
        is_active=True,
        organization_id=organization.id,
        target_engineer_id=engineer.id,
        conditions=[],
    )
    db.add(rule)
    db.commit()

    _, engineer_id = routing.resolve_assignment(db, organization.id, None)
    assert engineer_id == engineer.id


def test_inactive_rule_is_skipped(db: Session, organization: Organization, engineer: User):
    rule = _rule(db, conditions=[{"field": "organization", "value": organization.id}], engineer_id=engineer.id)
    rule.is_active = False
    db.add(rule)
    db.commit()

    assert routing.resolve_assignment(db, organization.id, None) == (None, None)


def test_no_match_leaves_the_ticket_in_the_common_queue(db: Session, organization: Organization, engineer: User):
    _rule(db, conditions=[{"field": "priority", "value": "P1"}], engineer_id=engineer.id)
    assert routing.resolve_assignment(db, organization.id, None, priority="P4") == (None, None)


# --- защита от неработающего правила ------------------------------------


def test_same_field_twice_with_all_is_rejected():
    """«Организация = А И организация = Б» не совпадёт никогда — это молча
    неработающее правило, и лучше не дать его сохранить."""
    from pydantic import ValidationError

    from app.schemas.routing import RoutingRuleCreate

    with pytest.raises(ValidationError):
        RoutingRuleCreate(
            order=1,
            rule_type=RoutingRuleType.ORGANIZATION_TO_ENGINEER,
            conditions=[
                {"field": "organization", "value": 1},
                {"field": "organization", "value": 2},
            ],
        )


def test_repeated_negations_are_allowed():
    """«Кроме А и кроме Б» — осмысленное правило."""
    from app.schemas.routing import RoutingRuleCreate

    rule = RoutingRuleCreate(
        order=1,
        rule_type=RoutingRuleType.ORGANIZATION_TO_ENGINEER,
        conditions=[
            {"field": "organization", "value": 1, "negate": True},
            {"field": "organization", "value": 2, "negate": True},
        ],
    )
    assert len(rule.conditions) == 2


# --- предпросмотр -------------------------------------------------------


def test_preview_shows_which_rule_wins(db: Session, organization: Organization, engineer: User):
    """Ошибка в маршрутизации обнаруживается не сразу: заявка просто уходит
    не туда. Проверка без создания заявки — способ убедиться заранее."""
    from app.api.routers.routing_rules import RoutingPreviewRequest, preview_routing

    _rule(db, conditions=[{"field": "priority", "value": "P1"}], engineer_id=engineer.id)

    hit = preview_routing(RoutingPreviewRequest(organization_id=organization.id, priority="P1"), db=db, _=None)
    assert hit["matched"] is True
    assert hit["target"] == engineer.full_name
    assert hit["target_kind"] == "engineer"

    miss = preview_routing(RoutingPreviewRequest(organization_id=organization.id, priority="P4"), db=db, _=None)
    assert miss["matched"] is False
