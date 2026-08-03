"""Индексы под очередь, отчёты и дашборд.

До этой миграции на tickets был только первичный ключ и уникальность номера:
любой фильтр по дате, статусу или организации разворачивался в полный
просмотр таблицы. На тестовых объёмах это незаметно, на годовом (182 тыс.
заявок) месячный отчёт занимал около 3 секунд.

Индексы выбраны по фактическим запросам, а не «на всякий случай»: каждый
из них замедляет вставку, а заявки создаются постоянно.

Revision ID: c3e91a5d70f4
Revises: b6d2f4a90c81
"""

from alembic import op

revision = "c3e91a5d70f4"
down_revision = "b6d2f4a90c81"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Очередь и «поток за неделю» сортируют и фильтруют по дате создания.
    op.create_index("ix_tickets_created_at", "tickets", ["created_at"])

    # Дашборд, бэклог и почти каждый экран отбирают открытые заявки; в паре
    # с датой это же закрывает «сколько закрыли за период».
    op.create_index("ix_tickets_status_created_at", "tickets", ["status", "created_at"])
    op.create_index("ix_tickets_closed_at", "tickets", ["closed_at"])
    op.create_index("ix_tickets_resolved_at", "tickets", ["resolved_at"])

    # Отчёт клиенту и портал всегда ограничены одной организацией.
    op.create_index("ix_tickets_organization_created_at", "tickets", ["organization_id", "created_at"])

    # «Мои заявки» инженера и виджет загрузки.
    op.create_index("ix_tickets_assigned_engineer_id", "tickets", ["assigned_engineer_id"])

    # Переписка заявки грузится по ticket_id при каждом открытии карточки,
    # а поиск по тексту ходит по messages через EXISTS.
    op.create_index("ix_messages_ticket_id", "messages", ["ticket_id"])

    # Списания времени за период — основа отчёта и биллинга.
    op.create_index("ix_time_entries_entry_date", "time_entries", ["entry_date"])
    op.create_index("ix_time_entries_ticket_id", "time_entries", ["ticket_id"])

    # Внешние ключи на tickets без индексов. Postgres при удалении заявки
    # проверяет каждую ссылающуюся таблицу полным перебором, и для
    # self-reference `parent_ticket_id` это перебор самих tickets на каждую
    # удаляемую строку — удаление становится квадратичным (обнаружено при
    # очистке нагрузочных данных: 182 тыс. заявок не удалились за полчаса).
    # Этот же индекс нужен панели «связанные заявки», которая ищет потомков.
    op.create_index("ix_tickets_parent_ticket_id", "tickets", ["parent_ticket_id"])
    op.create_index("ix_notifications_ticket_id", "notifications", ["ticket_id"])
    op.create_index("ix_calls_ticket_id", "calls", ["ticket_id"])
    op.create_index("ix_monitoring_alerts_ticket_id", "monitoring_alerts", ["ticket_id"])
    op.create_index("ix_active_timers_ticket_id", "active_timers", ["ticket_id"])
    op.create_index(
        "ix_channel_conversation_states_active_ticket_id", "channel_conversation_states", ["active_ticket_id"]
    )
    op.create_index(
        "ix_channel_conversation_states_revive_parent_ticket_id",
        "channel_conversation_states",
        ["revive_parent_ticket_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_channel_conversation_states_revive_parent_ticket_id", table_name="channel_conversation_states"
    )
    op.drop_index("ix_channel_conversation_states_active_ticket_id", table_name="channel_conversation_states")
    op.drop_index("ix_active_timers_ticket_id", table_name="active_timers")
    op.drop_index("ix_monitoring_alerts_ticket_id", table_name="monitoring_alerts")
    op.drop_index("ix_calls_ticket_id", table_name="calls")
    op.drop_index("ix_notifications_ticket_id", table_name="notifications")
    op.drop_index("ix_tickets_parent_ticket_id", table_name="tickets")
    op.drop_index("ix_time_entries_ticket_id", table_name="time_entries")
    op.drop_index("ix_time_entries_entry_date", table_name="time_entries")
    op.drop_index("ix_messages_ticket_id", table_name="messages")
    op.drop_index("ix_tickets_assigned_engineer_id", table_name="tickets")
    op.drop_index("ix_tickets_organization_created_at", table_name="tickets")
    op.drop_index("ix_tickets_resolved_at", table_name="tickets")
    op.drop_index("ix_tickets_closed_at", table_name="tickets")
    op.drop_index("ix_tickets_status_created_at", table_name="tickets")
    op.drop_index("ix_tickets_created_at", table_name="tickets")
