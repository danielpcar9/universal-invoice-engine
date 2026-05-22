# Universal Invoice Engine Glossary

This glossary explains the concepts needed to defend the project end to end.

## Project Shape

### Universal Invoice Engine

A backend engine that receives invoice files, parses them, validates payment-critical data, stores a canonical representation, and eventually generates SEPA payment files.

Feynman version:

> It is a machine that turns messy invoice files into clean payment-ready data.

### AP

Accounts Payable.

Money the company owes to suppliers.

In this project, AP means:

```text
Supplier invoice received -> validate -> store -> prepare payment
```

### AR

Accounts Receivable.

Money customers owe to the company.

AR is intentionally out of MVP scope for now.

### MVP

Minimum Viable Product.

The smallest version that proves the core workflow:

```text
PEPPOL invoice -> parse -> deduplicate -> store -> SEPA payment file
```

### Full Roadmap

The long-term vision: AR, Open Banking, ERP connectors, VIES, XAdES, Schematron, Celery, Redis, and enterprise compliance.

For interviews:

> The full roadmap shows ambition. The MVP shows execution.

## API Concepts

### API

Application Programming Interface.

The contract other systems use to talk to your backend.

Example:

```text
POST /api/v1/ap/invoices/ingest
```

### REST

An API style where resources are exposed through URLs and HTTP methods.

Example:

```text
POST /invoices
GET /invoices/{id}
```

### Endpoint

A specific URL + method handled by the backend.

Example:

```text
POST /api/v1/ap/invoices/ingest
```

### API Versioning

Putting the API version in the contract so future breaking changes do not surprise clients.

Current style:

```text
/api/v1/...
```

Common styles:

```text
URL versioning: /api/v1/invoices
Header versioning: Accept: application/vnd.company.v1+json
Query versioning: /invoices?version=1
```

Why URL versioning here:

> It is simple, visible, easy to test, and good for a portfolio/backend API.

### Request ID

A unique ID attached to each request.

Why it matters:

> If a request fails in production, the request ID lets you find its logs.

### HTTP 409 Conflict

Used when the request is valid but conflicts with current server state.

In this project:

```text
Same invoice raw_hash already exists -> 409 Conflict
```

### HTTP 422 Unprocessable Content

Used when the file was accepted as input but cannot be parsed or validated as expected.

Example:

```text
Malformed XML invoice -> 422
```

### Rate Limiting

Limiting how many requests a client can send in a time window.

Example:

```text
100 requests per minute per API key
```

Common implementation:

```text
Redis + token bucket -> return 429 Too Many Requests
```

For this MVP:

> Understand it and mention it as future protection. Do not implement it yet.

## Security Concepts

### API Key

A static secret sent by the client, often in a header.

Example:

```text
X-API-Key: sk_test_...
```

Why this project uses an API key placeholder:

> This is a backend-to-backend API. API keys are a simple first contract before adding tenants, DB-backed keys, and rotation.

### OAuth 2.0

A delegated authorization protocol.

Used when users or apps grant access to another app.

Example:

```text
Connect my bank account through an approved provider
```

Why not now:

> OAuth 2.0 is necessary for Open Banking or user-facing integrations, but overkill for this AP ingestion MVP.

### JWT

JSON Web Token.

A signed token that carries claims like user ID, tenant ID, or permissions.

Good for:

```text
stateless user sessions
microservices
short-lived access tokens
```

Why not now:

> The current MVP is service-to-service. API keys are enough for the first protected endpoint.

### Session Auth

Server-side session storage, usually cookie-based.

Good for browser apps.

Why not now:

> This project has no frontend and no browser login flow.

### XXE

XML External Entity attack.

A malicious XML can try to read local files or call network resources.

Defense in this project:

```text
disable entity resolution
disable DTD loading
disable network access
```

### XAdES

XML Advanced Electronic Signatures.

Used for digital signatures in XML documents.

Why out of MVP:

> It requires real certificate and trust-chain handling. Mention as enterprise/future compliance.

## Database Concepts

### DB

Database.

The place where the backend remembers durable state.

In this project:

```text
Postgres stores invoices and their hashes.
```

### Postgres

A relational database with strong SQL support and useful features like JSONB, indexes, transactions, and constraints.

Why Postgres:

> It handles structured finance records and flexible canonical JSON in the same system.

### SQLAlchemy

Python toolkit/ORM for talking to SQL databases.

Why SQLAlchemy here:

> It gives explicit control over models, sessions, constraints, async DB access, and future migrations.

### SQLModel

A library that combines Pydantic and SQLAlchemy.

Why not here:

> Good for CRUD prototypes, but this project benefits from separating API schemas, parser models, DB models, and domain logic.

### asyncpg

Async Postgres driver for Python.

Used through:

```text
postgresql+asyncpg://...
```

### greenlet

A small library SQLAlchemy uses internally to bridge sync-style ORM operations with async execution.

Why it was added:

> The async SQLAlchemy engine needed it when connecting and running DB operations.

### DATABASE_URL

Connection string that tells the app where the database lives.

Example:

```text
postgresql+asyncpg://uie_app:uie_password@localhost:5432/universal_invoice_engine
```

### Engine

The SQLAlchemy object that manages database connectivity.

Feynman version:

> The engine is the database connection factory.

### Session

A short-lived unit of work with the database.

Feynman version:

> A session is one conversation with Postgres.

### bind

In `async_sessionmaker(bind=engine)`, `bind` means:

> Use this engine when sessions need to talk to the database.

### pool_pre_ping

SQLAlchemy option that checks whether a DB connection is still alive before using it.

Why it matters:

> Long-running apps can hold stale DB connections. `pool_pre_ping=True` avoids using dead connections.

### expire_on_commit

SQLAlchemy option.

With `expire_on_commit=False`, objects keep their values after commit.

Why useful:

> After inserting an invoice, we can still read fields like `invoice.id` without forcing another DB reload.

### Migration

A versioned database schema change.

Example:

```text
Create invoices table
Add raw_hash unique index
Add tenant_id column
```

### Alembic

Migration tool commonly used with SQLAlchemy.

Current status:

> Installed, but not configured yet. The DB model exists first; migration wiring can be a focused follow-up commit.

### JSONB

Postgres binary JSON type.

Why this project uses it:

> Invoice data can vary by format and country. JSONB lets us store canonical invoice data flexibly while still using Postgres.

### UUID vs Auto-Increment IDs

Auto-increment IDs look like this:

```text
1, 2, 3, 4, 5
```

They are simple in one database because the database can always hand out the next number.

The problem appears in distributed systems:

```text
Database A gives ID 10
Database B also gives ID 10
collision
```

To avoid coordination problems, this project uses UUIDs:

```python
id: Mapped[uuid.UUID] = mapped_column(
    UUID(as_uuid=True),
    primary_key=True,
    default=uuid.uuid4,
)
```

Feynman version:

> Auto-increment IDs require one authority to hand out the next number. UUIDs can be generated independently by each API instance without asking a central counter.

Why this project uses UUIDs:

> For the MVP, auto-increment would work. But UUIDs are a low-cost choice that avoid future coordination issues if invoice ingestion becomes distributed.

What this project does not need:

```text
Snowflake IDs
central ticket server
custom distributed ID generator
```

Those are useful at massive scale, but overkill for this MVP.

Interview answer:

> I use UUIDs instead of auto-increment IDs because they avoid coordination problems in future distributed ingestion. I do not need Snowflake IDs at this stage; UUIDs are simpler and good enough for this system.

### raw_hash

SHA-256 hash of the original uploaded file.

Why it matters:

> It is the file fingerprint used for duplicate detection and auditability.

### UNIQUE Constraint

A database rule that prevents duplicate values.

In this project:

```text
raw_hash UNIQUE
```

Why DB-level uniqueness matters:

> It protects against race conditions where two requests try to insert the same invoice at the same time.

### Index

Data structure that makes lookups faster.

In this project:

```text
index on raw_hash
```

Why:

> Duplicate checks should be fast.

### Transaction

A group of DB operations that succeed or fail together.

Example:

```text
insert invoice -> commit
if duplicate -> rollback
```

### IntegrityError

SQLAlchemy error raised when the database rejects a rule violation.

Example:

```text
raw_hash already exists
```

The repository turns it into:

```text
DuplicateInvoiceError
```

## Finance Ops Concepts

### Invoice

A document requesting payment for goods or services.

### PEPPOL

Pan-European e-procurement network/spec ecosystem.

In this project:

> PEPPOL/UBL XML is the first supported structured invoice input.

### UBL

Universal Business Language.

An XML standard for business documents like invoices.

### EN16931

European standard for e-invoice semantics.

MVP approach:

> Implement basic payment-critical validation now; leave full Schematron compliance for later.

### Schematron

Rule-based XML validation language.

Why out of MVP:

> Full EN16931 Schematron is large and compliance-heavy. The MVP can prove the pattern without implementing every official rule.

### VAT

Value Added Tax.

A tax added to goods/services in Europe.

### VAT ID

Company tax identifier for VAT.

Future validation:

```text
VIES lookup
```

### VIES

EU system for checking VAT numbers.

Why future:

> External API, rate limits, availability concerns, and caching needs.

### IBAN

International Bank Account Number.

Used for European bank transfers.

MVP validation:

> Check format and checksum locally with math/library validation.

### BIC

Bank Identifier Code.

Identifies the bank in international payments.

### SEPA

Single Euro Payments Area.

Makes euro payments standardized across participating countries.

### pain.001

ISO 20022 XML message for customer credit transfer initiation.

In plain terms:

> A SEPA payment instruction file that a company can send/upload to a bank.

### CAMT.054

ISO 20022 bank notification message for account transactions.

Useful for reconciliation, but out of MVP for now.

### Reconciliation

Matching payments to invoices.

Example:

```text
Bank transaction for EUR 1200 -> invoice INV-2026-0001
```

### DSO

Days Sales Outstanding.

How long customers take to pay invoices.

Mostly AR, out of MVP.

## System Design Concepts

### Latency

How long one request takes.

Example:

```text
Upload invoice -> response in 180ms
```

### p95 Latency

95th percentile latency.

Meaning:

> 95% of requests are faster than this number.

Do not claim a p95 until measured.

### Throughput

How many requests the system can handle per time unit.

Example:

```text
50 requests per second
```

Do not claim throughput until load tested.

### DAU

Daily Active Users.

For this project, API usage may be better measured as:

```text
invoices/day
invoices/minute
API requests/minute
```

### Scale Expectations

For an MVP:

```text
single API instance
single Postgres instance
low-to-moderate invoice volume
```

For future:

```text
multiple API instances
background workers
queue-based parsing
DB indexes and read replicas
```

### Tradeoff

A decision where gaining one thing costs another.

Example:

```text
Parse synchronously in request -> simpler, but higher request latency
Queue parsing in background -> more scalable, but more moving parts
```

### DB Overload

When the database receives more queries/connections than it can handle.

Mitigations:

```text
connection pooling
indexes
rate limiting
queues
caching
read replicas
```

### Cache

Temporary fast storage, often Redis.

Useful for:

```text
VAT lookup results
rate limiting counters
idempotency keys
```

### Cache Failure

When Redis/cache is unavailable.

Design question:

> Does the system fail closed, fail open, or degrade gracefully?

For this MVP:

> No cache yet. Simpler and easier to reason about.

### Queue

System for background work.

Example:

```text
API receives invoice -> queue parsing job -> worker processes invoice
```

### Queue Backlog

When jobs arrive faster than workers process them.

Symptoms:

```text
delayed processing
increasing queue length
stale results
```

Future mitigation:

```text
add workers
prioritize jobs
dead-letter queues
backpressure
```

### Backpressure

Slowing or rejecting new work when the system is overloaded.

Example:

```text
return 429 or 503 when queue is too deep
```

### Idempotency

Doing the same operation twice has the same effect as doing it once.

In this project:

```text
Same invoice raw_hash twice -> one DB row, second request gets duplicate response
```

Feynman version:

> Idempotency means retries are safe. If the client sends the same operation again because of a timeout, the system should not accidentally create duplicate side effects.

Example:

```text
Client uploads invoice.xml
Server saves invoice
Network fails before client receives response
Client retries upload
System recognizes it and avoids creating a duplicate invoice
```

Related concepts in this project:

```text
raw_hash deduplication
Idempotency-Key
```

`raw_hash` answers:

```text
Have I seen this exact file before?
```

`Idempotency-Key` answers:

```text
Have I already processed this exact client request before?
```

Difference:

```text
raw_hash = identity of the file
idempotency key = identity of the operation
```

For the MVP:

> `raw_hash UNIQUE` is enough for file-based invoice deduplication.

For future payment operations:

> Add explicit `Idempotency-Key` support, especially for SEPA generation, because payment-related retries must not create duplicate side effects.

### Idempotency-Key

A client-provided unique key that identifies one write operation.

Usually sent as an HTTP header:

```text
Idempotency-Key: 6f4c1b8e-9a2d-4a33-a07f-123456789abc
```

Why it matters:

> If the client retries the same request after a timeout, the server can return the original result instead of performing the operation again.

In this project, it is most useful for future endpoints like:

```text
POST /api/v1/ap/invoices/ingest
POST /api/v1/ap/payments/sepa/generate
```

It is especially important for payment generation:

```text
Without idempotency key:
same retry -> possible duplicate payment file

With idempotency key:
same retry -> same response, no duplicate side effect
```

Interview answer:

> For invoice upload, I use `raw_hash` because the uploaded file itself has a stable identity. For payment generation, I would add explicit `Idempotency-Key` support because the operation, not just the input file, needs retry protection.

### Observability

Ability to understand what the system is doing from logs, metrics, and traces.

Current project pieces:

```text
structured logs
request ID
clear HTTP errors
```

### Structured Logging

Logs in a consistent machine-readable shape.

Why:

> Easier to search by request_id, path, status, and error.

### Health Check

Endpoint that tells infrastructure whether the app is alive.

Current route:

```text
GET /api/v1/health
```

### Docker Compose

Tool for running local services.

Current use:

```text
Postgres for local development
```

### Healthcheck

Docker check that confirms the service is actually ready.

For Postgres:

```text
pg_isready
```

## Interview Framing

### Honest MVP Pitch

> I scoped the project down to a realistic AP workflow: ingest a PEPPOL invoice, parse it safely, deduplicate by raw file hash, store a canonical JSON representation, validate payment-critical fields, and generate a SEPA pain.001 payment file.

### What To Avoid Saying

Do not say:

```text
I solved European finance operations.
```

Say:

```text
I implemented a focused slice of a real European AP automation problem.
```

### Strong Design Answer

> I enforce duplicate detection at the database layer with a UNIQUE constraint, not only in Python. That protects the system even under concurrent requests.
