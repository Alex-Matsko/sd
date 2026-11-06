"""Docker healthcheck, also callable by an external supervisor."""
import sys
from app.db import SessionLocal
from app.services.worker_health import healthy

if __name__ == "__main__":
    with SessionLocal() as db:
        sys.exit(0 if healthy(db) else 1)
