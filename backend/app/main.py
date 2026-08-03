from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
    notifications,
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
app.include_router(ws.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
