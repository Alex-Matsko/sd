from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import (
    assets,
    auth,
    calendars,
    categories,
    contacts,
    contracts,
    notifications,
    organizations,
    priority_matrix,
    routing_rules,
    tariffs,
    teams,
    tickets,
    users,
)
from app.config import settings

app = FastAPI(title="Открытые Горизонты — Service Desk API", version="0.1.0")

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


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
