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
```

Then, from the repo root:

```bash
npm start                     # backend on :8000 (auto-reload) + frontend on http://localhost:5173
```

`npm run start:api` and `npm run start:web` start just one of them. PostgreSQL must already be running.

## Tests

```bash
cd backend && .venv/bin/pytest     # needs an empty database at FAIDA_TEST_DATABASE_URL
cd frontend && npm test && npm run typecheck
```

The backend tests run against a real PostgreSQL database. The default is
`postgresql+psycopg://faida@localhost:5544/faida_test`. **The tests wipe that
database**, so never point `FAIDA_TEST_DATABASE_URL` at real data.

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
