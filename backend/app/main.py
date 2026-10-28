"""The Faida backend. The same code runs in two modes (masterplan 6):

- local: on the counter PC. Serves the counter screens' API, prints, and uploads every
  change to the cloud when the internet is there.
- cloud: on the shared Faida server. Receives uploads from every counter and serves the
  owners' phone view.
"""

from contextlib import asynccontextmanager
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from app.sync import outbox as _sync_queue  # noqa: F401  (registers the listener that queues every change)
from app import backup
from app.audit.router import router as audit_router
from app.auth.owner import LoginGuard
from app.auth.router import router as auth_router
from app.auth.sessions import KeypadGuard, SessionStore
from app.credit.router import router as credit_router
from app.expenses.router import router as cash_router
from app.floor.router import router as floor_router
from app.menu.router import router as menu_router
from app.payments.router import router as payments_router
from app.printing.models import PrinterName
from app.printing.printers import Printer, printer_or_none
from app.printing.router import router as printing_router
from app.printing.service import PrintService
from app.reports.mailer import MailWorker
from app.reports.phone import router as phone_router
from app.reports.router import router as reports_router
from app.settings.config import VERSION, Config, get_config
from app.settings.models import Business
from app.settings.router import router as settings_router
from app.shifts.router import router as shifts_router
from app.staff.router import router as staff_router
from app.stock.router import router as stock_router
from app.sync.health import router as admin_router
from app.sync.push import SyncClient, Transport, http_transport
from app.sync.receive import router as sync_router

COUNTER_ROUTERS = (
    auth_router, staff_router, settings_router, audit_router, menu_router, floor_router, payments_router,
    credit_router, shifts_router, cash_router, stock_router, reports_router, printing_router,
)
CLOUD_ROUTERS = (sync_router, phone_router, admin_router)


def create_app(
    config: Config | None = None,
    printers: dict[PrinterName, Printer] | None = None,
    sync_transport: Transport = http_transport,
    start_sync: bool = True,
) -> FastAPI:
    config = config or get_config()
    local = config.mode == "local"

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if app.state.sync and start_sync:
            app.state.sync.start(config.sync_interval_seconds)
        if local and config.smtp_host and start_sync:
            app.state.mail.start()
        yield
        if app.state.sync:
            app.state.sync.stop()
        app.state.mail.stop()
        app.state.printing.shutdown()

    app = FastAPI(title="Faida POS", version=VERSION, lifespan=lifespan)

    engine = create_engine(config.database_url, pool_pre_ping=True)
    app.state.config = config
    app.state.tz = ZoneInfo(config.timezone)
    app.state.engine = engine
    # In the cloud, rows arrive by sync and must not be queued again; a counter-only
    # install never uploads, so it doesn't queue either.
    app.state.sessionmaker = sessionmaker(engine, expire_on_commit=False,
                                          info={"no_sync_queue": not local or config.offline_only})
    app.state.sessions = SessionStore(idle_seconds=config.session_idle_minutes * 60)
    app.state.keypad = KeypadGuard(config.pin_max_attempts, config.pin_lockout_seconds)
    app.state.owner_logins = LoginGuard()
    app.state.printing = PrintService(app.state.sessionmaker, printers or {
        PrinterName.counter: printer_or_none(config.counter_printer if local else "none", "counter", config.counter_paper_mm),
        PrinterName.kitchen: printer_or_none(config.kitchen_printer if local else "none", "kitchen", config.kitchen_paper_mm),
    })
    app.state.mail = MailWorker(app.state.sessionmaker, config)
    app.state.sync = (
        SyncClient(app.state.sessionmaker, config.cloud_url, config.cloud_token, transport=sync_transport,
                   backup_status=lambda: backup.read_status(config))
        if local and config.cloud_url and config.cloud_token and not config.offline_only else None
    )

    api = APIRouter(prefix="/api")

    @api.get("/health", tags=["status"])
    def health() -> dict:
        """Public: the PIN screen shows the business name and status from here."""
        with app.state.sessionmaker() as db:
            db.execute(text("SELECT 1"))
            business = db.scalars(select(Business).limit(2)).all() if local else []
        sync = app.state.sync
        return {
            "mode": config.mode,
            "version": VERSION,
            "set_up": len(business) == 1,
            "business_name": business[0].name if len(business) == 1 else None,
            "cloud": ("off" if config.offline_only else "not_linked") if sync is None
                     else sync.status(config.sync_interval_seconds),
            "waiting_to_sync": sync.pending() if sync else None,
            "last_synced_at": sync.last_ok_at.isoformat() if sync and sync.last_ok_at else None,
            "printers": app.state.printing.status() if local else "not_set_up",
        }

    for router in COUNTER_ROUTERS if local else CLOUD_ROUTERS:
        api.include_router(router)
    app.include_router(api)

    if config.static_dir and Path(config.static_dir).is_dir():
        static = Path(config.static_dir)
        page = "index.html" if local else "phone.html"  # the cloud serves only the phone view
        app.mount("/assets", StaticFiles(directory=static / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            # Files at the top of the build (favicon, phone icon) as themselves; any other
            # path is a screen of the app.
            top = {f.name for f in static.iterdir() if f.is_file()}
            return FileResponse(static / path if path in top else static / page)

    return app
