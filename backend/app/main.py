from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.services import settings_audit  # noqa: F401 — подключает слушатель аудита настроек
from app.api.routers import (
    assets,
    auth,
    automation_rules,
    calendars,
    calls,
    categories,
    contacts,
    contracts,
    integration_settings,
    monitoring,
    perimetr,
    notifications,
    operations,
    work,
    organizations,
    portal,
    priority_matrix,
    client_reports,
    reports,
    response_templates,
    saved_filters,
    schedules,
    routing_rules,
    tariffs,
    teams,
    tickets,
    users,
    ws,
)
from app.config import settings, warn_about_insecure_settings

from app.services.realtime import hub


@asynccontextmanager
async def lifespan(_: FastAPI):
    warn_about_insecure_settings()
    # The LISTEN loop lives for the process, not per request - one database
    # connection shared by every websocket this process holds.
    hub.start()
    yield
    await hub.stop()


app = FastAPI(title="Открытые Горизонты — Service Desk API", version="0.1.0", lifespan=lifespan)

# allow_credentials выключен намеренно. Аутентификация здесь — заголовок
# Bearer, куки не используются, так что разрешать кросс-доменные запросы с
# учётными данными незачем. А в паре с allow_origins=["*"] Starlette
# отражает Origin запроса вместо звёздочки, то есть любой сайт получал бы
# право делать к API запросы с учётными данными — при появлении первой же
# куки это стало бы полноценной CSRF-дырой.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Total-Count", "Content-Disposition", "Retry-After"],
)


@app.middleware("http")
async def security_headers(request, call_next):
    """Заголовки, которых не было ни в одном ответе.

    Ставятся здесь, а не в nginx: перед API у заказчика может стоять свой
    прокси, а панель отдаётся отдельным контейнером — на уровне приложения
    заголовки не потеряются при смене обвязки.
    """
    response = await call_next(request)
    # Открывать панель и портал в чужом iframe незачем — это clickjacking.
    response.headers.setdefault("X-Frame-Options", "DENY")
    # Браузер не должен угадывать тип: вложение, отданное как text/plain, не
    # должно исполниться как HTML.
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    # API отдаёт только JSON и файлы; исполнять на его origin нечего.
    response.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
    return response

app.include_router(operations.router)
app.include_router(work.router)
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(organizations.router)
app.include_router(contacts.router)
app.include_router(contracts.router)
app.include_router(tariffs.router)
app.include_router(calendars.router)
app.include_router(priority_matrix.router)
app.include_router(categories.router)
app.include_router(assets.router)
app.include_router(teams.router)
app.include_router(routing_rules.router)
app.include_router(tickets.router)
app.include_router(notifications.router)
app.include_router(integration_settings.router)
app.include_router(automation_rules.router)
app.include_router(reports.router)
app.include_router(client_reports.router)
app.include_router(calls.router)
app.include_router(response_templates.router)
app.include_router(portal.router)
app.include_router(saved_filters.router)
app.include_router(schedules.router)
app.include_router(monitoring.router)
app.include_router(perimetr.router)
app.include_router(ws.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
