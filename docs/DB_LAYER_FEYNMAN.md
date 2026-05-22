# DB Layer Feynman Notes

## What This Commit Adds

This commit adds the first real persistence layer for the Universal Invoice Engine.

In plain terms:

> Before this commit, the API could receive and parse an invoice. After this commit, the backend has the building blocks to remember invoices in Postgres and reject duplicates by their file hash.

The flow this enables is:

```text
Uploaded invoice
  -> SHA-256 raw_hash
  -> Parsed/canonical invoice data
  -> Insert into Postgres
  -> If raw_hash already exists, raise DuplicateInvoiceError
```

## The Thinking Process

### 1. Start With The Smallest Useful DB Layer

The goal was not to build the entire persistence architecture in one commit.

The goal was:

```text
Connect to Postgres
Define the Invoice table
Insert an invoice
Detect duplicate raw_hash values
```

That is enough to move the project from "stateless parser API" to "stateful backend system."

### 2. Use SQLAlchemy Async, Not SQLModel

I chose SQLAlchemy directly because this project is not a simple CRUD app.

This project has domain transformations:

```text
XML upload -> parsed invoice -> canonical JSON -> DB row -> SEPA output
```

Keeping API schemas, parser models, domain data, and database models separate makes the system easier to reason about.

Interview answer:

> I considered SQLModel, but chose SQLAlchemy because this project needs explicit persistence control: unique constraints, async sessions, JSONB, transactions, and later migrations. SQLModel is great for CRUD prototypes; SQLAlchemy gives me lower-level control for a finance workflow.

### 3. Use `postgresql+asyncpg://`

The existing API is async, and FastAPI can handle concurrent requests efficiently.

For the database driver, that means the URL should use:

```text
postgresql+asyncpg://...
```

The `+asyncpg` part tells SQLAlchemy:

> Use the async Postgres driver, not the sync one.

That keeps the database layer aligned with the async API layer.

### 4. Add Alembic, But Do Not Configure Migrations Yet

I noticed Alembic was part of the intended stack, but it was not installed yet.

Senior decision:

> I can implement the DB layer without Alembic in this commit, then wire proper migrations in a later commit.

Why?

Because this commit is about the model and repository behavior. Alembic setup is its own concern:

```text
Commit now: DB model + repository
Later commit: migration scripts + alembic env
```

That keeps commits focused and easier to review.

### 5. Add A Small Schema Helper For Local Development

Because Alembic is not configured yet, I added:

```python
async def create_database_schema() -> None:
    from src.db.models import Base

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
```

Feynman explanation:

> This is a temporary local/dev helper that asks SQLAlchemy to create the tables from the models. It is useful before migrations exist. In production, Alembic should own schema changes.

This is intentionally not the final migration strategy.

### 6. Put Deduplication In The Database, Not Only In Python

The important column is:

```python
raw_hash: Mapped[str] = mapped_column(
    String(64),
    unique=True,
    index=True,
    nullable=False,
)
```

Feynman explanation:

> `raw_hash` is the invoice file fingerprint. If the same invoice file arrives twice, it produces the same hash. The database has a UNIQUE rule, so Postgres itself refuses duplicates.

This matters because Python-only duplicate checks can fail under concurrency.

Example race condition:

```text
Request A checks: hash does not exist
Request B checks: hash does not exist
Request A inserts
Request B inserts
```

Without a database `UNIQUE` constraint, both could be saved.

With `UNIQUE`, Postgres becomes the final authority.

### 7. Convert DB Errors Into Domain Errors

The repository catches SQLAlchemy's low-level error:

```python
except IntegrityError as exc:
    await session.rollback()
    existing_invoice = await get_invoice_by_raw_hash(session, raw_hash)
    existing_invoice_id = existing_invoice.id if existing_invoice else None
    raise DuplicateInvoiceError(raw_hash, existing_invoice_id) from exc
```

Feynman explanation:

> Postgres says "unique constraint failed." The repository translates that into something the application understands: "this invoice is a duplicate."

That keeps the API layer from needing to know database internals.

### 8. Run Checks After Each Meaningful Step

After implementing the DB layer, I ran:

```text
uv run ruff check .
uv run ty check
uv run pytest
```

Then I ran a smoke test against real Postgres:

```text
create schema
insert fake invoice
insert same invoice again
expect DuplicateInvoiceError
delete smoke row
```

Result:

```text
duplicate_detected=True
```

Feynman explanation:

> Static checks tell me the code is shaped correctly. Tests tell me existing behavior did not break. The DB smoke test proves the new persistence behavior works against real Postgres.

## What This Commit Does Not Do Yet

This commit does not connect the repository to the API endpoint yet.

Today:

```text
API parses invoice
Repository can save invoice
```

Next commit:

```text
API parses invoice
API calls repository
Duplicate raw_hash returns 409 Conflict
```

That next step is where the user-visible behavior changes.

## Interview Summary

> I added an async SQLAlchemy persistence layer with a Postgres-backed Invoice model. The key design decision is that duplicate detection is enforced by a database-level UNIQUE constraint on `raw_hash`, not just by application logic. I also kept migrations separate: this commit defines the model and repository behavior, while Alembic migration wiring belongs in a dedicated follow-up commit.
