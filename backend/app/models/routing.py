from sqlalchemy import Boolean, Enum as SAEnum, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import RoutingRuleType
from app.models.base import Base, TimestampMixin


class RoutingRule(Base, TimestampMixin):
    """Правило автоназначения (ТЗ 4.4).

    Правила проверяются по возрастанию `order`, побеждает первое подошедшее.

    Раньше правило было ровно одним условием: «организация → инженер» или
    «категория → группа». Для «заявки этого клиента по 1С — второй линии, но
    только не аварии» приходилось заводить несколько правил и надеяться на
    порядок. Теперь у правила есть **набор условий** (`conditions`) и
    указание, как их сочетать (`match`): все сразу или любое из них; каждое
    условие можно отдельно инвертировать.

    Полноценного дерева с вложенными скобками намеренно нет: на практике им
    почти не пользуются, зато конструктор становится непонятным, а ошибиться
    в нём легко. Сложный случай разбивается на два правила с разным
    приоритетом — это ещё и читается лучше.

    `rule_type`, `organization_id` и `category_id` оставлены ради правил,
    заведённых до появления условий: они продолжают работать как есть.
    """

    __tablename__ = "routing_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    order: Mapped[int] = mapped_column(Integer)
    name: Mapped[str | None] = mapped_column(String(255))
    rule_type: Mapped[RoutingRuleType] = mapped_column(
        SAEnum(RoutingRuleType, native_enum=False, length=30, validate_strings=True)
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    # "all" — должны совпасть все условия, "any" — достаточно одного.
    match: Mapped[str] = mapped_column(String(3), default="all", server_default="all")
    # [{"field": "organization", "op": "is", "value": 1, "negate": false}, ...]
    # JSONB, а не отдельная таблица: условия читаются и пишутся только
    # целиком вместе с правилом, а набор полей будет расширяться — колонка
    # на каждое поле означала бы миграцию при каждом добавлении.
    conditions: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")

    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"))
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))

    target_engineer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    target_team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"))
