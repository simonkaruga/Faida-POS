"""Sends tickets to printers without ever blocking or undoing a sale.

The sale is committed first. Each printer has one worker thread, so jobs print in
order. The request waits briefly so the screen usually shows the real result; if a
printer is slow or offline the ticket stays "Not printed" (orange) and the worker
updates it if the print does finish later.
"""

import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor, wait

from sqlalchemy.orm import sessionmaker

from app.db import now
from app.printing.document import Row, text
from app.printing.models import PrinterName, PrintStatus, Ticket
from app.printing.printers import Printer


class PrintService:
    def __init__(self, sessions: sessionmaker, printers: dict[PrinterName, Printer], wait_seconds: float = 2.5):
        self._sessions = sessions
        self._printers = printers
        self._wait = wait_seconds
        self._workers = {name: ThreadPoolExecutor(1, thread_name_prefix=f"print-{name}") for name in printers}
        self._lock = threading.Lock()
        self.last_result: dict[PrinterName, str] = {}

    def print_tickets(self, tickets: list[Ticket], reprint: bool = False) -> None:
        """Queue the tickets (already committed) and wait a moment for the results."""
        futures = [self._submit(t, reprint) for t in tickets]
        wait(futures, timeout=self._wait)

    def open_drawer(self) -> None:
        printer = self._printers[PrinterName.counter]
        self._workers[PrinterName.counter].submit(self._safe, printer.open_drawer)

    def status(self) -> str:
        with self._lock:
            return "offline" if "offline" in self.last_result.values() else "ok"

    def flush(self) -> None:
        """Wait until every queued job has finished."""
        wait([worker.submit(lambda: None) for worker in self._workers.values()])

    def shutdown(self) -> None:
        for worker in self._workers.values():
            worker.shutdown(wait=True)

    def _submit(self, ticket: Ticket, reprint: bool) -> Future:
        doc: list[Row] = list(ticket.content)
        copies = ticket.copies or [None]
        return self._workers[ticket.printer].submit(
            self._job, ticket.id, ticket.printer, doc, copies, reprint
        )

    def _safe(self, fn) -> None:
        try:
            fn()
        except Exception:
            pass

    def _job(self, ticket_id: uuid.UUID, printer: PrinterName, doc: list[Row], copies: list, reprint: bool) -> None:
        error = None
        try:
            for copy in copies:
                head = [text("*** REPRINT ***", bold=True, align="center")] if reprint else []
                if copy:
                    head.append(text(f"*** {copy} ***", bold=True, align="center"))
                self._printers[printer].print(head + doc)
        except Exception as e:  # any failure leaves the ticket "Not printed"
            error = str(e)[:200] or e.__class__.__name__
        with self._lock:
            self.last_result[printer] = "offline" if error else "ok"
        with self._sessions() as db:
            ticket = db.get(Ticket, ticket_id)
            if error:
                ticket.status = PrintStatus.not_printed
                ticket.last_error = error
            else:
                ticket.status = PrintStatus.printed
                ticket.printed_at = now()
                ticket.last_error = None
            db.commit()
