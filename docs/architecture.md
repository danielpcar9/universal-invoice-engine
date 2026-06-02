# Architecture

Universal Invoice Engine is a focused backend engine for European AP automation. It ingests invoices, extracts canonical data, stores that data idempotently, and generates SEPA payment XML.

It is not a full accounting platform. It is the backend engine that could sit inside one.

## System Boundary

```mermaid
flowchart TB
    External[Client / AP operator] --> API[FastAPI API]
    API --> InvoiceSvc[InvoiceService]
    API --> PaymentSvc[SepaPaymentService]
    InvoiceSvc --> Parser[PEPPOL parser]
    InvoiceSvc --> RepoPort[InvoiceRepositoryProtocol]
    PaymentSvc --> RepoPort
    PaymentSvc --> Iban[IBAN value object]
    PaymentSvc --> Sepa[SEPA generator]
    SqlRepo[SqlInvoiceRepository] -. implements .-> RepoPort
    SqlRepo --> DB[(PostgreSQL)]
    Alembic[Alembic migrations] --> DB
```

## Layers

```mermaid
flowchart TB
    API[API layer\nrouters, dependencies, HTTP errors]
    Services[Application services\nuse-case orchestration]
    Domain[Domain layer\nvalue objects, canonical types]
    Ports[Ports\nrepository contracts]
    Adapters[Infrastructure adapters\nSQLAlchemy repository]
    Persistence[Persistence\nPostgreSQL + JSONB + Alembic]

    API --> Services
    Services --> Domain
    Services --> Ports
    Adapters -. implement .-> Ports
    Adapters --> Persistence
```

### API Layer

- owns HTTP routes, request parsing, and response models
- keeps business rules out of routers
- translates domain exceptions into HTTP responses

### Application Services

- `InvoiceService` handles ingestion, validation, parsing, canonicalization, and persistence
- `SepaPaymentService` loads stored invoice data and generates payment XML
- services coordinate workflows but avoid direct SQLAlchemy calls

### Domain

- `InvoiceRepositoryProtocol` defines the persistence contract needed by services
- `IBAN` validates and normalizes account numbers before payment generation
- canonical invoice data provides a stable shape for downstream workflows

### Adapters and Persistence

- `SqlInvoiceRepository` adapts the repository protocol to SQLAlchemy
- `Invoice` is the PostgreSQL model
- `canonical_data` is stored as JSONB
- Alembic owns schema migrations

## Ingestion Flow

```mermaid
sequenceDiagram
    participant C as Client
    participant API as FastAPI Router
    participant S as InvoiceService
    participant P as PEPPOL Parser
    participant R as Repository
    participant DB as PostgreSQL

    C->>API: POST /ap/invoices/ingest
    API->>S: ingest(file)
    S->>S: validate filename, extension, size
    S->>S: compute SHA-256 raw_hash
    S->>P: parse XML
    P-->>S: ParsedInvoice
    S->>R: insert_invoice(raw_hash, canonical_data)
    R->>DB: INSERT invoices
    DB-->>R: stored invoice
    R-->>S: stored invoice
    S-->>API: InvoiceIngestResult
    API-->>C: 201 Created
```

Duplicate uploads are rejected by the unique `raw_hash` constraint. The repository translates that database conflict into a repository error, and `InvoiceService` translates it into a service-level duplicate error.

## SEPA Flow

```mermaid
sequenceDiagram
    participant C as Client
    participant API as FastAPI Router
    participant S as SepaPaymentService
    participant R as Repository
    participant I as IBAN
    participant G as SepaGenerator

    C->>API: POST /ap/payments/sepa/generate
    API->>S: generate_sepa(invoice_id, debtor account)
    S->>R: get_by_id(invoice_id)
    R-->>S: Invoice
    S->>S: validate canonical_data and amount
    S->>I: validate creditor_iban
    I-->>S: normalized IBAN
    S->>G: generate pain.001 XML
    G-->>S: XML bytes
    S-->>API: SepaGenerateResult
    API-->>C: 201 Created
```

## Idempotency

Idempotency is enforced with two layers:

- application layer computes `raw_hash = sha256(raw_bytes)`
- database layer enforces a unique index on `invoices.raw_hash`

The database is the source of truth. This avoids race-prone duplicate checks when multiple API instances exist.

## Schema Management

Alembic tracks schema evolution. The initial migration creates:

- `invoices.id`
- `invoices.raw_hash`
- `invoices.filename`
- `invoices.source_format`
- `invoices.canonical_data`
- `invoices.status`
- timestamps
- unique index on `raw_hash`

Useful commands:

```bash
uv run alembic upgrade head
uv run alembic current
uv run alembic check
```

## Design Tradeoffs

- **Synchronous processing** keeps the MVP simple, but heavy PDF/OCR parsing should move to background jobs.
- **JSONB canonical data** avoids premature schema rigidity, but important query fields may eventually deserve dedicated columns.
- **API key placeholder** is enough for local demo, but production needs real key management or OAuth2/JWT.
- **Single deployable service** is easier to operate now; clear boundaries make future extraction possible if volume requires it.

## Production Evolution

The most natural next steps are:

1. invoice status workflow and audit events
2. background workers for heavy parsing
3. tenant-aware API keys and data isolation
4. stricter PEPPOL/EN16931 compliance checks
5. raw file storage outside the relational database
