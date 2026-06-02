# Project Verification

This file records the commands used to verify the project locally before presenting or pushing changes.

## Current Status

- Backend API runs with FastAPI.
- PostgreSQL schema is managed through Alembic.
- Invoice ingestion, duplicate detection, PEPPOL parsing, IBAN validation, and SEPA generation are covered by tests.

## Verification Commands

```bash
docker-compose up -d postgres
uv run alembic upgrade head
uv run ruff check .
uv run pytest
uv run alembic check
```

Expected results:

```text
ruff: All checks passed.
pytest: 32 tests passed.
alembic check: No new upgrade operations detected.
```

## End-To-End Demo Checklist

1. Start PostgreSQL.
2. Apply Alembic migrations.
3. Start the API server.
4. Call `GET /api/v1/health`.
5. Ingest a PEPPOL XML invoice.
6. Upload the same invoice again and confirm `409 Conflict`.
7. Generate a SEPA payment file from the stored invoice.
8. Inspect the `invoices` table and `canonical_data` JSONB payload.

## Demo Commands

Start the API:

```bash
uv run uvicorn src.api.main:app --reload
```

Health check:

```bash
curl http://127.0.0.1:8000/api/v1/health
```

Expected response:

```json
{"status":"ok"}
```

Use `DEMO_GUIDE.md` for the full invoice ingestion and SEPA generation walkthrough.

## What To Emphasize

- This is a focused backend engine, not a full ERP/accounting SaaS.
- The architecture is a modular monolith with clear ports-and-adapters boundaries.
- Idempotency is enforced by PostgreSQL through a unique `raw_hash`.
- Alembic proves the schema is versioned rather than managed ad hoc.
- The next production steps would be audit events, workflow states, stronger auth, and background parsing jobs.

## Supporting Materials

- `README.md` - overview, scope, commands, and tradeoffs
- `docs/architecture.md` - diagrams and design rationale
- `DEMO_GUIDE.md` - live demo script
