# SD — сервис-деск для MSP «Открытые Горизонты»

Омниканальная сервис-деск система (multi-tenant, договоры, тарифные SLA, биллинг времени) по практикам ITIL 4. Разрабатывается с нуля поэтапно, каждый этап — работающий разворачиваемый результат.

## Документация

- [docs/TZ.md](docs/TZ.md) — техническое задание (включая план этапов в разделе 11)
- [docs/decisions.md](docs/decisions.md) — решения и уточнения, принятые по ходу разработки

## Статус

| Этап | Содержание | Статус |
|------|------------|--------|
| 1 | Ядро: модель данных, миграции, REST API, аутентификация, CRUD, статусная модель заявок, Docker Compose | ✅ Готов |
| 2 | Интерфейс сотрудника: очередь, карточка заявки, справочники, настройки | ✅ Готов |
| 3 | SLA-движок: таймеры, календари, паузы, эскалации | ⬜ Следующий |
| 4–10 | Email, Telegram/MAX, Plusofon, биллинг, портал клиента, отчёты, стабилизация | ⬜ |

## Стек

- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 16
- **Frontend:** React 18 + TypeScript, Vite, React Router, TanStack Query
- **Инфраструктура:** Docker Compose (app, db, nginx; с этапа 3 добавятся worker и redis), nginx как обратный прокси

## Структура проекта

```
sd/
├── docker-compose.yml        # Сервисы: db (PostgreSQL 16), app (backend), nginx
├── .env.example              # Шаблон конфигурации (скопировать в .env)
├── nginx/
│   └── nginx.conf            # Обратный прокси → app:8000
├── docs/
│   ├── TZ.md                 # Техническое задание
│   └── decisions.md          # Журнал решений по ходу разработки
├── backend/
│   ├── Dockerfile            # python:3.12-slim; при старте: alembic upgrade → seed → uvicorn
│   ├── requirements.txt      # Зависимости приложения
│   ├── requirements-dev.txt  # + pytest, httpx (для тестов)
│   ├── alembic.ini
│   ├── alembic/
│   │   └── versions/         # Миграции БД
│   ├── app/
│   │   ├── main.py           # FastAPI-приложение, подключение роутеров
│   │   ├── config.py         # Настройки (pydantic-settings, читает .env)
│   │   ├── db.py             # Engine и сессии SQLAlchemy
│   │   ├── seed.py           # Идемпотентный сид: справочники, календари, матрица
│   │   │                     #   приоритетов, тариф по умолчанию, первый админ
│   │   ├── core/             # Перечисления (enums), безопасность (JWT, bcrypt)
│   │   ├── models/           # SQLAlchemy-модели: organization, contact, contract,
│   │   │                     #   tariff, calendar, priority, category, asset, team,
│   │   │                     #   routing, ticket, message, time_entry, user, audit, auth
│   │   ├── schemas/          # Pydantic-схемы (зеркалят models)
│   │   ├── api/
│   │   │   ├── deps.py       # Зависимости: текущий пользователь, роли, сессия БД
│   │   │   └── routers/      # REST-роутеры: auth, users, organizations, contacts,
│   │   │                     #   contracts, tariffs, calendars, priority_matrix,
│   │   │                     #   categories, assets, teams, routing_rules, tickets
│   │   └── services/         # Бизнес-логика: tickets (статусная модель), routing,
│   │                         #   priority, billing, time_entries, messages,
│   │                         #   contracts, audit
│   └── tests/                # pytest: приоритеты, маршрутизация, биллинг,
│                             #   договоры, статусы заявок, безопасность
└── frontend/
    ├── package.json          # Скрипты: dev / build / lint
    ├── vite.config.ts
    └── src/
        ├── main.tsx, App.tsx # Точка входа, маршруты
        ├── api/              # HTTP-клиент, типы, эндпоинты
        ├── auth/             # Контекст аутентификации
        ├── layout/           # Каркас интерфейса (навигация)
        ├── components/       # UI-примитивы, иконки
        ├── lib/              # Русские подписи статусов/приоритетов и пр.
        ├── styles/           # Глобальные стили
        └── pages/
            ├── LoginPage, DashboardPage, TicketsPage,
            │   TicketDetailPage, NewTicketPage
            ├── directory/    # Организации, контакты, договоры, активы
            └── settings/     # Категории, матрица приоритетов,
                              #   правила маршрутизации, тарифы
```

При изменении структуры проекта (новые каталоги, сервисы, контейнеры) — обновлять этот раздел.

## Запуск локально

```bash
cp .env.example .env          # при необходимости поправить значения
docker compose up -d --build
```

- API и SPA доступны через nginx: http://localhost:8080 (порт — `HTTP_PORT` в `.env`)
- OpenAPI-документация: http://localhost:8080/docs
- Первый вход: `admin@o-horizons.com` / `ChangeMe123!` (задаётся `SEED_ADMIN_*` в `.env`; сменить после первого входа)

Миграции и сид выполняются автоматически при старте контейнера `app`.

Frontend в режиме разработки запускается отдельно (сборка в nginx — на этапе стабилизации):

```bash
cd frontend
npm install
npm run dev                   # http://localhost:5173, API берётся из VITE_API_BASE_URL
```

## Тестирование

**Все тесты выполняются в локальном Docker** — внутри контейнера `app`, не в локальном venv:

```bash
docker compose exec app sh -c "pip install -q -r requirements-dev.txt && python -m pytest tests/ -q"
```

Перед коммитом этапа тесты обязаны проходить полностью. Бизнес-логика SLA-расчётов и маршрутизации покрывается тестами обязательно (раздел 10 ТЗ).

## Конфигурация

Один файл `.env` в корне (см. [.env.example](.env.example)). Ключевые переменные:

| Переменная | Назначение | По умолчанию |
|------------|------------|--------------|
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | Доступ к PostgreSQL | `sd` / `sd` / `sd` |
| `HTTP_PORT` | Внешний порт nginx | `80` (локально используется `8080`) |
| `JWT_SECRET` | Секрет подписи токенов | `change-me` — обязательно сменить |
| `SEED_ADMIN_EMAIL` / `SEED_ADMIN_PASSWORD` | Первый администратор | `admin@o-horizons.com` / `ChangeMe123!` |
| `DEFAULT_TICKET_ATTACHMENT_LIMIT_MB` | Лимит размера вложения | `25` |

Полный список настроек — в [backend/app/config.py](backend/app/config.py).
