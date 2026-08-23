"""Автоназначение заявок (ТЗ 4.4).

Правила проверяются по возрастанию `order`, побеждает первое подошедшее.
Раньше правило было ровно одним условием, и «заявки этого клиента по 1С —
второй линии, но только не аварии» приходилось собирать из нескольких
правил, надеясь на их порядок. Теперь у правила набор условий и указание,
сочетать их через «и» или «или»; каждое условие можно инвертировать.
"""

from sqlalchemy.orm import Session

from app.core.enums import RoutingRuleType
from app.models.category import Category
from app.models.routing import RoutingRule

# Поля, по которым можно ставить условие. Список закрытый: свободное
# выражение в админке пришлось бы валидировать и объяснять пользователю, а
# выгоды на практике оно не даёт.
CONDITION_FIELDS = {
    "organization": "Организация",
    "category": "Категория",
    "channel": "Канал обращения",
    "priority": "Приоритет",
    "type": "Тип заявки",
    "asset": "Актив",
}


class TicketFacts:
    """Что известно о заявке на момент маршрутизации.

    Отдельный объект, а не сама заявка: правила применяются в момент
    создания, когда объекта ещё нет, и в предпросмотре, где заявки не будет
    вовсе.
    """

    def __init__(
        self,
        organization_id: int,
        category_id: int | None = None,
        channel: str | None = None,
        priority: str | None = None,
        ticket_type: str | None = None,
        asset_id: int | None = None,
        category_path: set[int] | None = None,
    ) -> None:
        self.organization_id = organization_id
        self.category_id = category_id
        self.channel = channel
        self.priority = priority
        self.ticket_type = ticket_type
        self.asset_id = asset_id
        # Категория совпадает и по родителю: правило на «1С» должно ловить
        # заявки в «1С → Обновление конфигурации».
        self.category_path = category_path or set()

    def value_of(self, field: str):
        return {
            "organization": self.organization_id,
            "category": self.category_id,
            "channel": self.channel,
            "priority": self.priority,
            "type": self.ticket_type,
            "asset": self.asset_id,
        }.get(field)


def _category_path(db: Session, category_id: int | None) -> set[int]:
    if category_id is None:
        return set()
    path = {category_id}
    category = db.get(Category, category_id)
    if category is not None and category.parent_id is not None:
        path.add(category.parent_id)
    return path


def _condition_matches(condition: dict, facts: TicketFacts) -> bool:
    field = condition.get("field")
    expected = condition.get("value")
    actual = facts.value_of(field)

    if field == "category":
        # Родитель тоже считается совпадением.
        values = expected if isinstance(expected, list) else [expected]
        hit = any(v in facts.category_path for v in values)
    elif isinstance(expected, list):
        # Список читается как «любое из»: «канал — Telegram или MAX» это
        # одно условие, а не два правила.
        hit = actual in expected
    else:
        hit = actual == expected

    return not hit if condition.get("negate") else hit


def rule_matches(rule: RoutingRule, facts: TicketFacts) -> bool:
    conditions = rule.conditions or []

    if not conditions:
        # Правило из старого формата, где условие задавалось колонками.
        # Поведение сохраняется в точности — заведённые правила продолжают
        # работать без переделки.
        if rule.rule_type == RoutingRuleType.ORGANIZATION_TO_ENGINEER:
            return rule.organization_id == facts.organization_id
        if rule.rule_type == RoutingRuleType.CATEGORY_TO_TEAM:
            return rule.category_id in facts.category_path
        return False

    results = [_condition_matches(c, facts) for c in conditions]
    return all(results) if (rule.match or "all") == "all" else any(results)


def resolve_assignment_for(db: Session, facts: TicketFacts) -> tuple[int | None, int | None]:
    """Возвращает (team_id, engineer_id); заполнено не больше одного.
    (None, None) — ни одно правило не подошло, заявка идёт в общую очередь
    диспетчера."""
    rules = db.query(RoutingRule).filter(RoutingRule.is_active.is_(True)).order_by(RoutingRule.order).all()
    for rule in rules:
        if not rule_matches(rule, facts):
            continue
        if rule.target_engineer_id:
            return None, rule.target_engineer_id
        if rule.target_team_id:
            return rule.target_team_id, None
    return None, None


def resolve_assignment(
    db: Session,
    organization_id: int,
    category_id: int | None,
    channel: str | None = None,
    priority: str | None = None,
    ticket_type: str | None = None,
    asset_id: int | None = None,
) -> tuple[int | None, int | None]:
    """Прежняя сигнатура сохранена: её зовут из создания заявки и из тестов.
    Дополнительные признаки необязательны — правила, которые их не
    используют, работают как прежде."""
    facts = TicketFacts(
        organization_id=organization_id,
        category_id=category_id,
        channel=channel,
        priority=priority,
        ticket_type=ticket_type,
        asset_id=asset_id,
        category_path=_category_path(db, category_id),
    )
    return resolve_assignment_for(db, facts)
