# DB Layer Feynman Notes

## What this document explains

This notes file describes the current persistence architecture of Universal Invoice Engine.

The active design is:

```text
InvoiceService -> InvoiceRepositoryProtocol -> SqlInvoiceRepository -> SQLAlchemy -> Postgres
```

The database layer stores canonical invoice data and enforces deduplication based on raw file hashes.

## Current persistence design

### 1. Domain and repository separation

The database is behind a port: `src/domain/ports/invoice_repository.py`.

This protocol defines the persistence contract:

- `insert_invoice(...)`
- `get_by_id(...)`

That means application services depend on an abstract repository, not on SQLAlchemy directly.

In the current code:

- `src/api/dependencies/services.py` creates a `SqlInvoiceRepository` and injects it into services
- `src/services/invoice_service.py` and `src/services/sepa_payment_service.py` consume the repository through `InvoiceRepositoryProtocol`

This is the hexagonal/ports-and-adapters pattern in practice.

### 2. SQLAlchemy model shape

The database model is defined in `src/db/models.py`.

The invoice row contains:

- `id`: UUID primary key
- `raw_hash`: SHA-256 of the uploaded file content
- `filename`: original filename
- `source_format`: file extension or source format
- `canonical_data`: JSONB payload with normalized invoice data
- `status`: invoice lifecycle state (default `received`)
- `created_at`, `updated_at`: timestamps

The key property is `raw_hash`:

```python
raw_hash: Mapped[str] = mapped_column(
    String(64),
    unique=True,
    index=True,
    nullable=False,
)
```

This means Postgres enforces deduplication at the database level.

### 3. Why `canonical_data` is JSONB

The DB stores parsed invoice information as JSONB rather than as a rigid column set.

That choice supports:

- flexibility for different invoice sources
- auditability of the extracted canonical representation
- a simple path to AI/analytics ingestion
- slower schema migration pressure for early stages

In this code, `canonical_data` can hold a full `ParsedInvoice` model dump for PEPPOL XML, or a minimal metadata object for unsupported formats.

### 4. Deduplication in the DB, not just in Python

Idempotency is implemented as:

1. Compute SHA-256 over the raw uploaded bytes in `InvoiceService._compute_hash`
2. Persist the invoice row with `raw_hash`
3. If Postgres rejects the insert due to `unique(raw_hash)`, translate that failure into `DuplicateInvoiceError`

This is the correct senior design because the database becomes the final authority under concurrency.

### 5. Repository error translation

The repository layer catches SQLAlchemy's integrity error and converts it to a domain-level exception.

From `src/repositories/invoice_repository.py`:

```python
except IntegrityError as exc:
    await session.rollback()
    existing_invoice = await get_invoice_by_raw_hash(session, raw_hash)
    existing_invoice_id = existing_invoice.id if existing_invoice else None
    raise DuplicateInvoiceError(raw_hash, existing_invoice_id) from exc
```

This keeps the service layer free from DB internals and allows HTTP handlers to respond with a clean `409 Conflict` semantics.

### 6. Actual repository implementation

`src/repositories/sql_invoice_repository.py` is the adapter.

It delegates to the lower-level helper functions in `src/repositories/invoice_repository.py`.

This is a deliberate split:

- `SqlInvoiceRepository` is the adapter used at runtime
- the lower-level module contains the pure SQLAlchemy persistence logic and error handling

### 7. How the API layer uses the DB layer today

The HTTP endpoints are thin.

For invoice ingest:

- `src/api/routers/invoices.py` accepts the upload
- it calls `service.ingest(file)` on `InvoiceService`
- `InvoiceService` validates, parses, and builds `canonical_data`
- `InvoiceService._save_with_idempotency` calls the injected repository

For SEPA generation:

- `src/api/routers/payments.py` accepts the payment request
- it calls `service.generate_sepa(...)` on `SepaPaymentService`
- the service loads the invoice from the repository by `invoice_id`
- the service reads `canonical_data` and generates ISO 20022 XML

### 8. Why this is a good current architecture

The current DB layer is not overengineered.

It is:

- explicit: the domain depends on a protocol, not on SQLAlchemy
- defensible: Postgres enforces duplicate protection
- extensible: the repository can be swapped for a different adapter
- practical: JSONB stores normalized identity data without forcing a huge schema

### 9. What is not implemented here yet

The current code does not yet contain an Alembic migration setup.

That is fine for the current phase: the project has a working persistence model and a clear path to add migrations later.

This is a deliberate, senior-level choice: separate schema design from migration tooling.

## Interview-friendly summary

> The persistence layer is built around a clean port-and-adapter boundary. `InvoiceService` never talks to SQLAlchemy directly; it talks to `InvoiceRepositoryProtocol`. `SqlInvoiceRepository` adapts that protocol to a Postgres-backed SQLAlchemy model. Deduplication is enforced with a unique `raw_hash`, and database integrity failures are translated into domain exceptions so the API can handle them in a user-friendly way.
