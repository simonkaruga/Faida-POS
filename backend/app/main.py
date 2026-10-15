"""The Faida backend. The same code runs in two modes (masterplan 6):

- local: on the counter PC. Serves the counter screens' API, prints, queues sync.
- cloud: on the shared Faida server. Receives sync and serves the owner's phone view
  (built in Phase 5).
"""

from contextlib import asynccontextmanager
from zoneinfo import ZoneInfo

from fastapi import APIRouter, FastAPI
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from app.audit.router import router as audit_router
from app.auth.router import router as auth_router
from app.auth.sessions import KeypadGuard, SessionStore
from app.floor.router import router as floor_router
from app.menu.router import router as menu_router
from app.payments.router import router as payments_router
from app.printing.models import PrinterName
from app.printing.printers import Printer, make_printer
from app.printing.service import PrintService
from app.settings.config import VERSION, Config, get_config
from app.settings.models import Business
from app.settings.router import router as settings_router
from app.staff.router import router as staff_router

COUNTER_ROUTERS = (
    auth_router, staff_router, settings_router, audit_router, menu_router, floor_router, payments_router,
)


def create_app(config: Config | None = None, printers: dict[PrinterName, Printer] | None = None) -> FastAPI:
    config = config or get_config()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        app.state.printing.shutdown()

    app = FastAPI(title="Faida POS", version=VERSION, lifespan=lifespan)

    engine = create_engine(config.database_url, pool_pre_ping=True)
    app.state.config = config
    app.state.tz = ZoneInfo(config.timezone)
    app.state.engine = engine
    app.state.sessionmaker = sessionmaker(engine, expire_on_commit=False)
    app.state.sessions = SessionStore(idle_seconds=config.session_idle_minutes * 60)
    app.state.keypad = KeypadGuard(config.pin_max_attempts, config.pin_lockout_seconds)
    app.state.printing = PrintService(app.state.sessionmaker, printers or {
        PrinterName.counter: make_printer(config.counter_printer, "counter"),
        PrinterName.kitchen: make_printer(config.kitchen_printer, "kitchen"),
    })

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
            # Cloud sync arrives in Phase 5.
            "cloud": "not_linked",
            "printers": app.state.printing.status() if config.mode == "local" else "not_set_up",
        }

    if config.mode == "local":
        for router in COUNTER_ROUTERS:
            api.include_router(router)

    app.include_router(api)
    return app
