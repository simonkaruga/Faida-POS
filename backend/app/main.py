"""The Faida backend. The same code runs in two modes (masterplan 6):

- local: on the counter PC. Serves the counter screens' API, prints, queues sync.
- cloud: on the shared Faida server. Receives sync and serves the owner's phone view
  (built in Phase 5).
"""

from fastapi import APIRouter, FastAPI
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from app.audit.router import router as audit_router
from app.auth.router import router as auth_router
from app.auth.sessions import KeypadGuard, SessionStore
from app.settings.config import VERSION, Config, get_config
from app.settings.models import Business
from app.settings.router import router as settings_router
from app.staff.router import router as staff_router


def create_app(config: Config | None = None) -> FastAPI:
    config = config or get_config()
    app = FastAPI(title="Faida POS", version=VERSION)

    engine = create_engine(config.database_url, pool_pre_ping=True)
    app.state.config = config
    app.state.engine = engine
    app.state.sessionmaker = sessionmaker(engine, expire_on_commit=False)
    app.state.sessions = SessionStore(idle_seconds=config.session_idle_minutes * 60)
    app.state.keypad = KeypadGuard(config.pin_max_attempts, config.pin_lockout_seconds)

    api = APIRouter(prefix="/api")

    @api.get("/health", tags=["status"])
    def health() -> dict:
        """Public: the PIN screen shows the business name and status from here."""
        with app.state.sessionmaker() as db:
            db.execute(text("SELECT 1"))
            business = db.scalars(select(Business).limit(2)).all() if config.mode == "local" else []
        return {
            "mode": config.mode,
            "version": VERSION,
            "set_up": len(business) == 1,
            "business_name": business[0].name if len(business) == 1 else None,
            # Cloud sync and printers arrive in later phases.
            "cloud": "not_linked",
            "printers": "not_set_up",
        }

    if config.mode == "local":
        for router in (auth_router, staff_router, settings_router, audit_router):
            api.include_router(router)

    app.include_router(api)
    return app
