from app.core.enums import RoutingRuleType, UserRole
from app.core.security import hash_password
from app.models.category import Category
from app.models.routing import RoutingRule
from app.models.team import Team
from app.models.user import User
from app.services.routing import resolve_assignment


def _engineer(db, email):
    user = User(full_name="E", email=email, password_hash=hash_password("x"), role=UserRole.ENGINEER)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_no_rules_falls_back_to_dispatcher_queue(db, organization):
    team_id, engineer_id = resolve_assignment(db, organization.id, category_id=None)
    assert (team_id, engineer_id) == (None, None)


def test_organization_rule_wins_over_category_rule(db, organization):
    """docs/decisions.md assumption: a rule scoped to a specific organization is
    more specific than a category rule and is evaluated first when both would
    match, by giving it the lower `order`."""
    engineer = _engineer(db, "dedicated@o-horizons.com")
    team = Team(name="Общая команда")
    db.add(team)
    db.flush()
    category = Category(name="Сервер")
    db.add(category)
    db.flush()

    db.add(
        RoutingRule(
            order=1,
            rule_type=RoutingRuleType.ORGANIZATION_TO_ENGINEER,
            organization_id=organization.id,
            target_engineer_id=engineer.id,
        )
    )
    db.add(
        RoutingRule(
            order=2,
            rule_type=RoutingRuleType.CATEGORY_TO_TEAM,
            category_id=category.id,
            target_team_id=team.id,
        )
    )
    db.commit()

    team_id, engineer_id = resolve_assignment(db, organization.id, category_id=category.id)
    assert (team_id, engineer_id) == (None, engineer.id)


def test_category_rule_matches_via_parent_category(db, organization):
    team = Team(name="1С")
    db.add(team)
    db.flush()
    parent = Category(name="1С")
    db.add(parent)
    db.flush()
    child = Category(name="Обновление конфигурации", parent_id=parent.id)
    db.add(child)
    db.flush()

    db.add(RoutingRule(order=1, rule_type=RoutingRuleType.CATEGORY_TO_TEAM, category_id=parent.id, target_team_id=team.id))
    db.commit()

    team_id, engineer_id = resolve_assignment(db, organization.id, category_id=child.id)
    assert (team_id, engineer_id) == (team.id, None)


def test_first_matching_rule_by_order_wins(db, organization):
    team_a = Team(name="A")
    team_b = Team(name="B")
    db.add_all([team_a, team_b])
    db.flush()
    category = Category(name="Категория")
    db.add(category)
    db.flush()

    db.add(RoutingRule(order=5, rule_type=RoutingRuleType.CATEGORY_TO_TEAM, category_id=category.id, target_team_id=team_b.id))
    db.add(RoutingRule(order=1, rule_type=RoutingRuleType.CATEGORY_TO_TEAM, category_id=category.id, target_team_id=team_a.id))
    db.commit()

    team_id, _ = resolve_assignment(db, organization.id, category_id=category.id)
    assert team_id == team_a.id


def test_inactive_rule_is_ignored(db, organization):
    engineer = _engineer(db, "inactive-rule@o-horizons.com")
    db.add(
        RoutingRule(
            order=1,
            rule_type=RoutingRuleType.ORGANIZATION_TO_ENGINEER,
            organization_id=organization.id,
            target_engineer_id=engineer.id,
            is_active=False,
        )
    )
    db.commit()

    team_id, engineer_id = resolve_assignment(db, organization.id, category_id=None)
    assert (team_id, engineer_id) == (None, None)
