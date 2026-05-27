# Universal Invoice Engine

Backend API-first for Accounts Payable automation with PEPPOL invoice ingestion and SEPA payment generation.

## Problem statement

European finance teams receive invoices in mixed formats and need a reliable way to:

- ingest invoices safely,
- normalize data consistently,
- prevent duplicate invoice ingestion,
- generate SEPA payment files for bank processing.

## What this project does

- accepts invoice files through `POST /api/v1/ap/invoices/ingest`
- parses PEPPOL XML into a canonical invoice model
- persists invoice metadata and canonical payloads in PostgreSQL JSONB
- enforces idempotency via raw file hashing
- generates ISO 20022 `pain.001` SEPA XML from ingested invoices

## Why this architecture matters

This repository is intentionally designed as a modular monolith, not as a distributed system full of unrelated services.

### Core architectural patterns

- **Thin API boundary**: FastAPI routers delegate business rules to services.
- **Application services**: `InvoiceService` and `SepaPaymentService` orchestrate domain flows.
- **Ports & Adapters**: `InvoiceRepositoryProtocol` defines domain contracts while `SqlInvoiceRepository` provides the infrastructure implementation.
- **Value objects**: `IBAN` encapsulates bank account validation and normalization.
- **Canonical data**: `canonical_data` normalizes invoices into a stable shape for downstream systems.

## High-level architecture

- `src/api/routers`: HTTP endpoints with request validation and response models.
- `src/services/invoice_service.py`: invoice ingestion, validation, parsing, and persistence orchestration.
- `src/services/sepa_payment_service.py`: invoice loading, payment validation, and SEPA XML generation.
- `src/domain/value_objects`: domain value objects such as IBAN.
- `src/domain/ports`: repository contracts required by the application.
- `src/repositories/sql_invoice_repository.py`: PostgreSQL/SQLAlchemy persistence adapter.
- `src/db/models.py`: invoice database model with unique `raw_hash`.

See `docs/architecture.md` for architecture diagrams and flow details.

## Why PEPPOL + SEPA

- **PEPPOL** is the European standard for electronic B2B invoicing.
- **SEPA** is the standard for euro credit transfers.

This project covers a real financing workflow: converting invoice data into executable payment instructions.

## Design tradeoffs

- Simplicity over premature distribution
- Modular monolith over microservices
- JSONB flexibility over rigid schema enforcement
- Explicit domain services over fat routers
- Synchronous processing for MVP simplicity

## Why JSONB?

- invoices vary significantly by source
- canonical schemas evolve over time
- PEPPOL and custom formats may diverge
- JSONB enables flexible ingestion without destructive migrations

This is a fintech-real choice: store a stable reference payload while allowing the invoice model to adapt.

## Local development

1. Create and activate virtual environment

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

2. Run the application

```bash
uvicorn src.api.main:app --reload
```

3. Run tests

```bash
pytest
```

## AI-native narrative

The system is designed for AI-native finance operations because:

- `canonical_data` is normalized and structured
- the ingestion pipeline produces consistent financial objects
- downstream AI workflows can consume a stable schema
- separation of ingestion and persistence enables enrichment before payment

## Roadmap

- async ingestion queue for PDF/CSV and large files
- OCR + extraction for unstructured invoices
- AI-based vendor enrichment and normalization
- anomaly detection for suspicious invoices
- supplier/entity deduplication
- stateful orchestration for multi-stage payment flows

## Learn more

- `docs/architecture.md`
