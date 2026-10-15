"""Counter side: upload the sync queue to the cloud whenever the internet is there.

Selling never waits for this. If the cloud can't be reached the queue just grows, and
the top bar shows "Offline"; the next successful upload catches up in order.
"""

import json
import logging
import threading
import urllib.error
import urllib.request
from collections import defaultdict
from collections.abc import Callable
from datetime import datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import sessionmaker

from app.db import Base, SyncStatus, now
from app.settings.config import VERSION
from app.sync.models import SyncQueueEntry

log = logging.getLogger("faida.sync")

Transport = Callable[[str, dict, str], dict]


class SyncError(Exception):
    pass


def http_transport(url: str, body: dict, token: str) -> dict:
    request = urllib.request.Request(
        url, data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as e:
        raise SyncError(f"Cloud refused the upload ({e.code}): {e.read()[:200].decode(errors='replace')}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise SyncError(f"Cloud not reachable: {e}") from e


class SyncClient:
    def __init__(self, sessions: sessionmaker, cloud_url: str, token: str, *, transport: Transport = http_transport,
                 batch: int = 500, backup_status: Callable[[], dict] = dict):
        self._sessions = sessions
        self._url = cloud_url.rstrip("/") + "/api/sync/upload"
        self._token = token
        self._transport = transport
        self._batch = batch
        self._backup_status = backup_status
        self.last_ok_at: datetime | None = None
        self.last_error: str | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def pending(self) -> int:
        with self._sessions() as db:
            return db.scalar(select(func.count()).select_from(SyncQueueEntry))

    def push_once(self) -> int:
        """Upload one batch. Returns how many entries the cloud accepted (0: nothing to do)."""
        with self._sessions() as db:
            entries = db.scalars(select(SyncQueueEntry).order_by(SyncQueueEntry.seq).limit(self._batch)).all()
            body = {
                "software_version": VERSION,
                "counter_time": now().isoformat(),
                "backup": self._backup_status(),
                "entries": [dict(seq=e.seq, table=e.table_name, op=e.op, id=str(e.row_id), data=e.payload)
                            for e in entries],
            }
            try:
                result = self._transport(self._url, body, self._token)
            except SyncError as e:
                self.last_error = str(e)
                raise
            accepted = int(result["accepted_up_to"])
            done = [e for e in entries if e.seq <= accepted]
            by_table: dict[str, set] = defaultdict(set)
            for e in done:
                if e.op == "upsert":
                    by_table[e.table_name].add(e.row_id)
            for name, ids in by_table.items():
                table = Base.metadata.tables[name]
                db.execute(update(table).where(table.c.id.in_(ids)).values(sync_status=SyncStatus.synced.value))
            db.execute(delete(SyncQueueEntry).where(SyncQueueEntry.seq <= accepted))
            db.commit()
            self.last_ok_at, self.last_error = now(), None
            return len(done)

    def push_all(self) -> int:
        total = 0
        while sent := self.push_once():
            total += sent
        return total

    def status(self, interval: float) -> str:
        """Online if the last upload attempt worked and wasn't long ago."""
        if self.last_error is None and self.last_ok_at and (now() - self.last_ok_at).total_seconds() < interval * 3 + 30:
            return "online"
        return "offline"

    def start(self, interval: float) -> None:
        def loop():
            while not self._stop.is_set():
                try:
                    self.push_all()
                except Exception as e:  # keep trying; the counter works without the cloud
                    self.last_error = self.last_error or str(e)
                    log.warning("sync: %s", self.last_error)
                self._stop.wait(interval)

        self._thread = threading.Thread(target=loop, name="faida-sync", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
