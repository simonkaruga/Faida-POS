"""Emails the daily closing to the owner (and anyone she adds), with the Excel copy.

Closing the day only queues the email, so it works offline; a worker sends queued
emails whenever the internet is there and keeps retrying until they go.
"""

import html
import logging
import smtplib
import threading
from collections.abc import Callable
from email.message import EmailMessage

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.db import now
from app.reports.models import EmailOutbox
from app.settings.config import Config

log = logging.getLogger("faida.mail")

Sender = Callable[[Config, EmailMessage], None]
MAX_ATTEMPTS = 50


def smtp_send(config: Config, message: EmailMessage) -> None:
    with smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=20) as smtp:
        smtp.starttls()
        if config.smtp_user:
            smtp.login(config.smtp_user, config.smtp_password or "")
        smtp.send_message(message)


def k(n: int | None) -> str:
    return f"KSh {n or 0:,}"


def closing_html(business: str, report: dict) -> str:
    s, box = report["sales"], report["cash_box"]
    row = lambda label, value, bold=False: (  # noqa: E731
        f"<tr><td style='padding:4px 12px 4px 0'>{'<b>' if bold else ''}{html.escape(label)}{'</b>' if bold else ''}</td>"
        f"<td style='padding:4px 0;text-align:right'>{'<b>' if bold else ''}{value}{'</b>' if bold else ''}</td></tr>")
    rows = [row("Sales", k(s["total"]), True), row("Cash", k(s["cash"])), row("M-Pesa", k(s["mpesa"])),
            row("Card", k(s.get("card"))), row("Credit", k(s["credit"])), row("Bills", s["bills"]),
            row("Credit collected", k(report["credit_collected"]["total"])),
            row("Cash box should hold", k(box["expected_now"]), True)]
    if "profit" in report:
        rows.append(row("Real profit", k(report["profit"]["real_profit"]), True))
    alerts = [f"{w['staff']} short {k(-w['difference'])}" for w in report["shortages"]]
    if report["voids"]:
        alerts.append(f"{len(report['voids'])} items removed after sending ({k(report['void_total'])})")
    if report.get("comps", {}).get("total"):
        alerts.append(f"Free items: {k(report['comps']['total'])} at menu price")
    alerts += [f"{u['place']}: {k(u['amount'])} unpaid ({u['waiter']} responsible)" for u in report["unpaid_bills"]]
    alerts += [f"{v['item']}: {v['variance']}" for v in report["stock_variance"] if v["variance"].startswith("Missing")]
    alert_html = "".join(f"<li>{html.escape(a)}</li>" for a in alerts) or "<li>Nothing to flag.</li>"
    return (f"<div style='font-family:Arial,sans-serif;font-size:15px;color:#0b1733'>"
            f"<h2 style='margin:0 0 4px'>{html.escape(business)}: daily closing</h2>"
            f"<p style='margin:0 0 16px;color:#55627f'>Business day {report['day']}. The full report is attached (Excel).</p>"
            f"<table>{''.join(rows)}</table><h3>Needs attention</h3><ul>{alert_html}</ul>"
            f"<p style='color:#55627f;font-size:13px'>Sent by Faida POS. Not a KRA tax invoice.</p></div>")


def queue_closing(db: Session, config: Config, business: str, to: list[str], report: dict, workbook: bytes) -> bool:
    """Queue the closing email if there is anyone to send to. Returns whether it was queued."""
    if not to:
        return False
    db.add(EmailOutbox(to=to, subject=f"{business}: daily closing {report['day']} – sales {k(report['sales']['total'])}",
                       html=closing_html(business, report), attachment_name=f"closing-{report['day']}.xlsx",
                       attachment=workbook))
    return True


def send_pending(sessions: sessionmaker, config: Config, sender: Sender = smtp_send) -> int:
    """Send every queued email that hasn't gone yet. Returns how many went."""
    if not config.smtp_host:
        return 0
    sent = 0
    with sessions() as db:
        for mail in db.scalars(select(EmailOutbox).where(EmailOutbox.sent_at.is_(None), EmailOutbox.attempts < MAX_ATTEMPTS)
                               .order_by(EmailOutbox.created_at)):
            message = EmailMessage()
            message["Subject"] = mail.subject
            message["From"] = config.smtp_from or config.smtp_user or "faida@localhost"
            message["To"] = ", ".join(mail.to)
            message.set_content("This email needs a viewer that shows HTML.")
            message.add_alternative(mail.html, subtype="html")
            if mail.attachment:
                message.add_attachment(mail.attachment, maintype="application",
                                       subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                       filename=mail.attachment_name)
            mail.attempts += 1
            try:
                sender(config, message)
                mail.sent_at, mail.last_error = now(), None
                sent += 1
            except (OSError, smtplib.SMTPException) as e:
                mail.last_error = str(e)[:300]
                log.warning("mail: %s", mail.last_error)
            db.commit()
    return sent


class MailWorker:
    def __init__(self, sessions: sessionmaker, config: Config, sender: Sender = smtp_send):
        self._sessions, self._config, self._sender = sessions, config, sender
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self, interval: float = 60) -> None:
        def loop():
            while not self._stop.is_set():
                try:
                    send_pending(self._sessions, self._config, self._sender)
                except Exception as e:  # keep going; the counter works without email
                    log.warning("mail: %s", e)
                self._stop.wait(interval)

        self._thread = threading.Thread(target=loop, name="faida-mail", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
