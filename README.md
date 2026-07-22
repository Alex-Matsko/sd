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
| 3 | SLA-движок: таймеры, календари, паузы, эскалации 75%/100%, in-app уведомления | ✅ Готов |
| 4 | Email (вход/выход, склейка диалога) + универсальные настройки каналов | 🟡 Email готов; уведомления инженерам в Telegram — остаток этапа |
| 5 | Канал MAX для клиентов: идентификация, диалог, «Мои заявки», очередь неопознанных, CSAT | 🟡 MAX готов (не проверен на боевом токене); Telegram-клиент — остаток этапа |
| 6–10 | Plusofon, биллинг, портал клиента, отчёты, стабилизация | ⬜ |

## Стек

- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 16
- **Frontend:** React 18 + TypeScript, Vite, React Router, TanStack Query
- **Инфраструктура:** Docker Compose (app, worker, db, nginx), nginx как обратный прокси. Worker — отдельный процесс на том же образе backend, раз в минуту считает SLA-эскалации (`app/worker.py`); Redis появится, когда понадобится (websocket pub-sub, очереди каналов — этапы 4+)

## Структура проекта

```
sd/
├── docker-compose.yml        # Сервисы: db (PostgreSQL 16), app (backend), worker (SLA + email), nginx
├── .env.example              # Шаблон конфигурации (скопировать в .env)
├── nginx/
│   └── nginx.conf            # Обратный прокси → app:8000
├── docs/
│   ├── TZ.md                 # Техническое задание
│   └── decisions.md          # Журнал решений по ходу разработки
├── backend/
│   ├── Dockerfile            # python:3.12-slim; при старте (app): alembic upgrade → seed → uvicorn;
│   │                         #   worker переопределяет CMD на `python -m app.worker`
│   ├── requirements.txt      # Зависимости приложения
│   ├── requirements-dev.txt  # + pytest, httpx (для тестов)
│   ├── alembic.ini
│   ├── alembic/
│   │   └── versions/         # Миграции БД (initial schema; stage3 sla engine;
│   │                         #   stage4 email channel; stage5 MAX channel)
│   ├── app/
│   │   ├── main.py           # FastAPI-приложение, подключение роутеров
│   │   ├── config.py         # Настройки (pydantic-settings, читает .env) — только
│   │   │                     #   инфраструктурные параметры; интеграции каналов
│   │   │                     #   теперь в БД (integration_settings), см. ниже
│   │   ├── db.py             # Engine и сессии SQLAlchemy
│   │   ├── seed.py           # Идемпотентный сид: справочники, календари, матрица
│   │   │                     #   приоритетов, тариф по умолчанию, первый админ,
│   │   │                     #   докатка SLA-сроков для заявок до Этапа 3
│   │   ├── worker.py         # Фоновый процесс: SLA-эскалации (раз в минуту, главный
│   │   │                     #   цикл) + опрос почты (свой интервал, тот же цикл) +
│   │   │                     #   long polling MAX (отдельный поток, не блокирует SLA)
│   │   ├── core/             # Перечисления (enums), безопасность (JWT, bcrypt),
│   │   │                     #   crypto (шифрование секретов интеграций)
│   │   ├── models/           # SQLAlchemy-модели: organization, contact, contract,
│   │   │                     #   tariff, calendar, priority, category, asset, team,
│   │   │                     #   routing, ticket, message, time_entry, user, audit,
│   │   │                     #   auth, notification, integration_setting,
│   │   │                     #   channel_conversation_state
│   │   ├── schemas/          # Pydantic-схемы (зеркалят models)
│   │   ├── api/
│   │   │   ├── deps.py       # Зависимости: текущий пользователь, роли, сессия БД
│   │   │   └── routers/      # REST-роутеры: auth, users, organizations, contacts,
│   │   │                     #   contracts, tariffs, calendars, priority_matrix,
│   │   │                     #   categories, assets, teams, routing_rules, tickets,
│   │   │                     #   notifications, integration_settings
│   │   └── services/         # Бизнес-логика: tickets (статусная модель), routing,
│   │                         #   priority, billing, time_entries, messages,
│   │                         #   contracts, audit, calendar_math (рабочее время
│   │                         #   по бизнес-календарю), sla (SLA-движок Этапа 3),
│   │                         #   integration_settings (универсальное хранилище
│   │                         #   настроек каналов), email_channel (IMAP/SMTP,
│   │                         #   склейка диалога), max_client + max_channel (Bot API
│   │                         #   MAX, диалог, «Мои заявки», CSAT), unknown_queue
│   │                         #   (общая очередь «Неизвестные» email+MAX),
│   │                         #   attachments (общее хранилище вложений)
│   └── tests/                # pytest: приоритеты, маршрутизация, биллинг,
│                             #   договоры, статусы заявок, безопасность,
│                             #   SLA-движок, email-канал, MAX-канал
└── frontend/
    ├── package.json          # Скрипты: dev / build / lint
    ├── vite.config.ts
    └── src/
        ├── main.tsx, App.tsx # Точка входа, маршруты
        ├── api/              # HTTP-клиент, типы, эндпоинты
        ├── auth/             # Контекст аутентификации
        ├── layout/           # Каркас интерфейса (навигация, колокольчик уведомлений)
        ├── components/       # UI-примитивы (статус/приоритет/SLA-теги), иконки
        ├── lib/              # Русские подписи статусов/приоритетов/SLA и пр.
        ├── styles/           # Глобальные стили
        └── pages/
            ├── LoginPage, DashboardPage, TicketsPage (SLA-колонка, фильтр риска),
            │   TicketDetailPage (панель SLA), NewTicketPage
            ├── directory/    # Организации, контакты, договоры, активы
            └── settings/     # Категории, матрица приоритетов,
                              #   правила маршрутизации, тарифы, каналы
                              #   (Email и MAX — рабочие формы; Telegram/
                              #   телефония — заглушки под будущие этапы)
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
| `SLA_WARNING_THRESHOLD` | Доля бюджета SLA для эскалации-предупреждения | `0.75` |
| `WORKER_INTERVAL_SECONDS` | Периодичность прохода воркера SLA-эскалаций | `60` |
| `SETTINGS_ENCRYPTION_KEY` | Ключ шифрования секретов интеграций (Fernet, urlsafe-base64 32 байта) | небезопасный dev-ключ — сгенерировать свой перед вводом реальных учётных данных |

Полный список настроек — в [backend/app/config.py](backend/app/config.py).

## Настройка каналов (Email, MAX и далее)

Учётные данные интеграций (IMAP/SMTP ящика поддержки, токен MAX-бота, в будущем — Telegram, Plusofon) задаются **в интерфейсе**, не в `.env`: Настройки → Каналы (`/settings/channels`, роль руководитель/администратор). Хранятся в таблице `integration_settings` — несекретные поля в открытом виде, пароли/токены зашифрованы `SETTINGS_ENCRYPTION_KEY` (см. выше) и никогда не возвращаются через API в открытом виде (только флаг «задан»). Это сделано специально, чтобы новый канал не требовал перевыпуска `.env` и передеплоя — только запись в БД через форму.

Email: приём — IMAP-опрос (интервал задаётся в настройках канала, независим от интервала SLA-эскалаций), отправка — SMTP с тегом `[#OH-<номер>]` в теме письма. Правила склейки диалога и очереди «Неизвестные» — раздел 2.3 ТЗ и [docs/decisions.md](docs/decisions.md).

MAX: приём и отправка — long polling Bot API MAX (`platform-api2.max.ru`), идентификация по MAX ID контакта, «Мои заявки»/«Создать новую» как кнопки, запрос оценки (CSAT) при закрытии заявки. **Важно:** интеграция написана по официальной документации без проверки на боевом токене бота (референсный бридж заказчика не был доведён до конца) — перед вводом в эксплуатацию обязательно завести тестового бота и сверить реальный формат событий с разбором в [backend/app/services/max_channel.py](backend/app/services/max_channel.py), см. подробности в [docs/decisions.md](docs/decisions.md).
