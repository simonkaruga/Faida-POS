# Faida POS

Offline-first point of sale for a bar and restaurant. What it does and why is in
[docs/masterplan.md](docs/masterplan.md).

- `backend/`: Python + FastAPI. It holds every rule, all money logic and all data, and runs in **local** (counter) or **cloud** mode.
- `frontend/`: React + TypeScript touchscreen app.

## Development

You need Python 3.11+, Node 20+ and PostgreSQL 16.

One-time setup:

```bash
npm install                   # root: the tool that runs both servers
(cd frontend && npm install)
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env          # set FAIDA_PIN_SECRET and FAIDA_DATABASE_URL
.venv/bin/alembic upgrade head
.venv/bin/python -m app.cli init-business --name "Demo Bar" --owner "Njeri"
.venv/bin/python -m app.cli load-menu ../docs/sample-menu.json   # menu and tables
```

Then, from the repo root:

```bash
npm start      # counter backend :8000, cloud backend :8100, frontend http://localhost:5173
```

`npm run start:api`, `start:cloud` and `start:web` start just one of them. PostgreSQL
must already be running.

- Counter screens: http://localhost:5173
- Owner's phone view: http://localhost:5173/phone.html (try it in the browser's phone mode)

### The development cloud

The cloud is the same backend in cloud mode (`backend/.env.cloud`, see `.env.cloud.example`)
on its own database. Linking a counter and creating the owner's phone login:

```bash
cd backend
FAIDA_DATABASE_URL=<cloud database> .venv/bin/alembic upgrade head
set -a; . ./.env.cloud; set +a                  # cloud settings for the next commands
.venv/bin/python -m app.cli register-device --business-id <id> --name "Counter"
.venv/bin/python -m app.cli create-owner --business-id <id> --email owner@example.com
```

`register-device` prints `FAIDA_CLOUD_TOKEN=...` for the counter's `.env` (with
`FAIDA_CLOUD_URL`). `create-owner` prints a key to add to an authenticator app
(Google Authenticator, Microsoft Authenticator...), which then shows the 6-digit code
the phone login asks for.

Sync: every change at the counter is written to `sync_queue` in the same transaction
and uploaded in order when the cloud can be reached. The top bar shows Online, or
Offline with how many changes are waiting.

### Backups

```bash
.venv/bin/python -m app.backup create --to /media/usb/faida     # nightly
.venv/bin/python -m app.backup restore --file faida-local-20261016-040000.fbk
```

Backups hold the database and the PIN secret, encrypted with `FAIDA_BACKUP_PASSPHRASE`;
the newest 14 are kept. The result is sent to the cloud, and
`python -m app.cli check-health` (cloud, for cron) reports counters whose sync or
backups stopped, or whose clock is off.

In development nothing goes to a real printer: slips, tickets, bills and receipts are
written as text files to `backend/prints/`. Set `FAIDA_COUNTER_PRINTER` and
`FAIDA_KITCHEN_PRINTER` to use real printers (formats in
[printers.py](backend/app/printing/printers.py)).

## Tests

```bash
cd backend && .venv/bin/pytest     # needs an empty database at FAIDA_TEST_DATABASE_URL
cd frontend && npm test && npm run typecheck
```

The backend tests run against real PostgreSQL databases: `faida_test` (the counter),
`faida_cloud_test` (the cloud) and `faida_restore_test` (backup restores), on
`localhost:5544` by default (`FAIDA_TEST_DATABASE_URL`, `FAIDA_TEST_CLOUD_DATABASE_URL`,
`FAIDA_TEST_RESTORE_DATABASE_URL`). **The tests wipe those databases**, so never point
them at real data. Backup tests need `pg_dump` (`FAIDA_TEST_PG_BIN`).

## How permissions work

[backend/app/auth/permissions.py](backend/app/auth/permissions.py) is masterplan section 2
written as code, and the backend checks every request against it. Each action has one of four levels:

- `allow`: the role can always do it.
- `own`: only on the person's own bills.
- `approval`: an Owner or Supervisor must approve it with their PIN first.
- `deny`: the role can never do it.

For `approval` actions, the waiter's screen calls `POST /api/auth/approvals`, where the
approver types their PIN. The endpoint for the action then calls
`auth.service.authorize(...)` with that approval and records it with `audit.record(...)`.
That audit entry marks the approval as used, so it can't be used a second time.

Audit entries and approvals are permanent. A database trigger refuses any edit or delete;
only their sync status may change.
