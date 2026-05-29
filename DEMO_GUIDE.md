# Professional Demo Guide: Universal Invoice Engine

A structured walkthrough for presenting this project to a CTO or technical decision-maker.

---

## Part 0: Pre-Demo Checklist (5 minutes)

Before demoing to the CTO, verify everything locally:

### 1. Run Tests to Confirm Everything Works

```bash
# Activate virtual environment
source .venv/bin/activate

# Run all tests
pytest -v
```

Expected output: **All tests pass** (~10 tests covering parsing, API, validation, deduplication).

### 2. Start PostgreSQL (one-time setup)

```bash
# Start the Postgres container in docker-compose
docker-compose up -d postgres

# Verify it's ready (wait for "healthy" status)
docker-compose ps
```

### 3. Start the API Server

```bash
# In a separate terminal, ensure venv is activated
source .venv/bin/activate

# Run the development server
uvicorn src.api.main:app --reload
```

Expected output:
```
INFO:     Uvicorn running on http://127.0.0.1:8000
```

Now you're ready to demo.

---

## Part 1: Executive Summary (2 minutes)

**Opening statement for the CTO:**

> "This is a backend-API-first system for Accounts Payable automation. It solves a real European finance problem:
>
> - Teams receive invoices in mixed formats (PEPPOL/UBL XML, PDFs, CSVs)
> - They need one system to normalize, deduplicate, and prepare payment files
> - Today, this is manual; we've automated the critical path
>
> Three core capabilities:
> 1. **Invoice Ingestion** — PEPPOL XML parsing with idempotency
> 2. **Data Normalization** — Canonical JSON representation for downstream systems
> 3. **Payment Generation** — ISO 20022 pain.001 SEPA XML for bank upload"

---

## Part 2: Architecture Overview (3 minutes)

Show the CTO this diagram or verbally walk through:

**Data Flow:**

```
Invoice File (XML/PDF/CSV)
         ↓
    Ingest Endpoint (POST /api/v1/ap/invoices/ingest)
         ↓
    Validate Format & Size
         ↓
    Parse (PEPPOL → Python object)
         ↓
    Compute raw_hash SHA256
         ↓
    Check Duplicates (UNIQUE constraint + index)
         ↓
    Build Canonical JSON
         ↓
    Store in Postgres (JSONB + raw_hash)
         ↓
    Return invoice_id
         ↓
    [Later] Generate SEPA payment file
```

**Key architectural decisions:**

1. **Modular monolith** — All logic in one service, easy to reason about and test.
2. **Ports & Adapters** — Repository pattern enables swapping DB implementations.
3. **Value Objects** — `IBAN` class encapsulates financial validation.
4. **JSONB storage** — Flexible schema for varying invoice formats without destructive migrations.
5. **Idempotency** — `raw_hash` deduplication prevents duplicate payment ingestion.

See `docs/architecture.md` for diagrams.

---

## Part 3: Live Demo (8–10 minutes)

### 3a. API Health Check

```bash
curl -X GET http://127.0.0.1:8000/api/v1/health
```

Expected response:
```json
{"status": "ok"}
```

**CTO point:** "The API is live and responding with proper HTTP semantics."

---

### 3b. Upload a Valid PEPPOL Invoice

Use this sample XML:

```bash
cat > /tmp/invoice.xml << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
         xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
    <cbc:ID>INV-2026-0001</cbc:ID>
    <cbc:IssueDate>2026-05-20</cbc:IssueDate>
    <cbc:DocumentCurrencyCode>EUR</cbc:DocumentCurrencyCode>
    
    <cac:AccountingSupplierParty>
        <cac:Party>
            <cac:PartyName>
                <cbc:Name>Supplier Ltd</cbc:Name>
            </cac:PartyName>
        </cac:Party>
    </cac:AccountingSupplierParty>
    
    <cac:AccountingCustomerParty>
        <cac:Party>
            <cac:PartyName>
                <cbc:Name>Customer Corp</cbc:Name>
            </cac:PartyName>
        </cac:Party>
    </cac:AccountingCustomerParty>
    
    <cac:LegalMonetaryTotal>
        <cbc:TaxExclusiveAmount currencyID="EUR">1000.00</cbc:TaxExclusiveAmount>
        <cbc:TaxInclusiveAmount currencyID="EUR">1200.00</cbc:TaxInclusiveAmount>
        <cbc:PayableAmount currencyID="EUR">1200.00</cbc:PayableAmount>
    </cac:LegalMonetaryTotal>
</Invoice>
EOF
```

Upload it to the API:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/ap/invoices/ingest \
  -H "X-API-Key: test-key" \
  -F "file=@/tmp/invoice.xml"
```

Expected response (200 Created):
```json
{
  "invoice_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "filename": "invoice.xml",
  "size_bytes": 1024,
  "content_hash": "abc123def456...",
  "status": "received",
  "received_at": "2026-05-27T10:00:00Z",
  "parsed_invoice": {
    "invoice_id": "INV-2026-0001",
    "issue_date": "2026-05-20",
    "currency": "EUR",
    "supplier_name": "Supplier Ltd",
    "customer_name": "Customer Corp",
    "total_amount": "1200.00",
    "tax_amount": "200.00",
    ...
  }
}
```

**CTO point:**
- "The API accepted the invoice and returned a structured response."
- "The parser extracted all key fields into a normalized `ParsedInvoice` object."
- "Now this data is stored in the database for later retrieval or payment generation."

Save the `invoice_id` for the next step.

---

### 3c. Demonstrate Idempotency (Duplicate Detection)

Upload the same invoice file again:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/ap/invoices/ingest \
  -H "X-API-Key: test-key" \
  -F "file=@/tmp/invoice.xml"
```

Expected response (409 Conflict):
```json
{
  "detail": "Invoice with hash abc123... already exists",
  "raw_hash": "abc123...",
  "existing_invoice_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6"
}
```

**CTO point:**
- "Duplicate detection is automatic via SHA256 file hashing."
- "The database enforces a UNIQUE constraint on `raw_hash` to prevent race conditions."
- "This is idempotent: uploading the same file twice returns the same invoice_id (or a 409 if already exists)."
- "In a distributed system, this pattern prevents invoice double-charging."

---

### 3d. Show Canonical Data Storage

Query the database (optional, if CTO wants to verify):

```bash
# Connect to Postgres
PGPASSWORD=uie_password psql -U uie_app -h localhost -d universal_invoice_engine

# In psql:
SELECT id, raw_hash, status, canonical_data FROM invoices LIMIT 1;
```

Expected output:
```
                   id                   |         raw_hash         | status |          canonical_data
----------------------------------------+--------------------------+--------+-------------------------------
 3fa85f64-5717-4562-b3fc-2c963f66afa6 | abc123def456... | received | {"invoice_id": "INV-2026-0001", ...}
(1 row)
```

**CTO point:**
- "Canonical data is stored as JSONB, which gives us both flexibility (for varied invoice formats) and queryability (for future analytics)."
- "The raw file hash is indexed for O(1) duplicate lookups."

---

### 3e. Generate a SEPA Payment File (Optional Advanced Demo)

Once an invoice is ingested, generate a SEPA payment file:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/sepa/generate \
  -H "X-API-Key: test-key" \
  -H "Content-Type: application/json" \
  -d '{
    "invoice_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "debtor_name": "My Company",
    "debtor_iban": "DE89370400440532013000",
    "debtor_bic": "COBADEFFXXX"
  }'
```

Expected response (200 OK):
```json
{
  "payment_id": "PAY-ABC123DEF456",
  "invoice_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "xml_payload": "<?xml version=\"1.0\"...pain.001...?>",
  "amount": "1200.00",
  "currency": "EUR",
  "creditor_iban": "...",
  "generated_at": "2026-05-27T10:00:00Z"
}
```

**CTO point:**
- "We generate ISO 20022 pain.001 XML, the standard format for SEPA credit transfers."
- "The system validates IBANs and enforces payment currency (EUR only for SEPA)."
- "The output is ready to upload directly to your bank."

---

## Part 4: Code Quality & Testing (3 minutes)

Show the CTO:

### 4a. Run Tests

```bash
pytest -v --tb=short
```

Output should show:
- ✓ `test_health_check`
- ✓ `test_ingest_valid_xml`
- ✓ `test_duplicate_invoice_returns_409`
- ✓ `test_malformed_xml_returns_422`
- ✓ `test_iban_validation`
- ✓ `test_compliance_scorer`
- ✓ `test_peppol_parser`

**CTO point:**
- "All critical flows are tested: parsing, validation, deduplication, error handling."
- "Test coverage includes happy paths and error cases (malformed XML, duplicates, invalid IBANs)."

### 4b. Code Organization

Walk through the directory structure:

```
src/
├── api/              # HTTP layer (routers, dependencies, exception handlers)
├── services/         # Business logic (invoice ingestion, SEPA payment)
├── repositories/     # Data access layer (insert, query, deduplication)
├── db/               # Database models and session management
├── domain/           # Domain logic (value objects, ports)
└── core/             # Configuration (settings)

docs/
└── architecture.md   # Architecture diagrams and rationale
```

**CTO point:**
- "Clear separation of concerns: API boundary, business logic, persistence, domain."
- "Easy to test in isolation, easy to extend or replace implementations."

---

## Part 5: Design Decisions Q&A (5 minutes)

**Anticipated CTO questions:**

### Q1: "Why not microservices?"
**Answer:** "The MVP benefits from monolithic simplicity. We've used Ports & Adapters, so extracting services later (e.g., a payment processor microservice) is straightforward. Today, a single codebase is faster to deploy and reason about."

### Q2: "How does this handle high volume?"
**Answer:** "For MVP: single API instance, single Postgres. For scale:
- Horizontal: add API instances behind a load balancer.
- DB: connection pooling, indexes on `raw_hash`, read replicas.
- Async: queue-based parsing (Celery/Redis) for bursty workloads.
- Each layer decouples, so scaling is targeted."

### Q3: "What about compliance? EN16931, Schematron?"
**Answer:** "MVP validates payment-critical fields (IBAN, amounts, dates). Full EN16931 Schematron compliance is out of scope. We can add rule-based validation (compliance scorer) incrementally. The architecture supports it."

### Q4: "How is this GDPR/security-proof?"
**Answer:** "At MVP: API key placeholder (will be database-backed with rotation). HTTPS in production. DB connection string encrypted. XXE protection in XML parsing. Planned: tenant isolation, audit logging, encryption-at-rest."

### Q5: "Why PEPPOL + SEPA and not a generic ETL?"
**Answer:** "PEPPOL and SEPA are the standards for European B2B finance. This project is domain-specific: we solve invoicing → payment reliably rather than attempting a generic ETL."

---

## Part 6: Roadmap & Next Steps (2 minutes)

**What's implemented (MVP):**
- ✅ PEPPOL/UBL XML parsing
- ✅ Canonical data storage (JSONB)
- ✅ Idempotency via `raw_hash` deduplication
- ✅ SEPA pain.001 generation
- ✅ IBAN validation
- ✅ API key placeholder

**What's next (Phase 2):**
- 🔲 Database-backed API keys with rotation
- 🔲 Tenant isolation (`tenant_id` scoping)
- 🔲 Compliance scoring (EN16931 rules)
- 🔲 Celery + Redis for background parsing
- 🔲 CAMT.054 support (bank statements for reconciliation)
- 🔲 VIES VAT lookup (async external API)

**Why this order?**
- Tenant isolation unblocks multi-customer deployment.
- Compliance scoring gates payment generation approval.
- Background jobs enable bursty invoice uploads.

---

## Part 7: Q&A & Next Actions (5 minutes)

**Ask the CTO:**
1. "Does the architecture align with your vision for AP automation?"
2. "What are your top concerns (security, scale, compliance, observability)?"
3. "Would you integrate this into an existing ERP/financial platform?"

**Next steps (if interested):**
- Code review with your engineering team
- Security audit (especially API key, data access, XXE)
- Load test: simulate 100+ invoices/minute
- Pilot with a real invoice vendor (e.g., Basware, Coupa)

---

## Appendix: Useful Commands for Demo

### Start the stack

```bash
# Terminal 1: Start Postgres
docker-compose up -d postgres
sleep 5

# Terminal 2: Activate venv and start API
source .venv/bin/activate
uvicorn src.api.main:app --reload

# Terminal 3: Run tests in another shell
source .venv/bin/activate
pytest -v
```

### Test endpoints quickly

```bash
# Health check
curl http://127.0.0.1:8000/api/v1/health

# Upload invoice (save response to see invoice_id)
RESPONSE=$(curl -s -X POST http://127.0.0.1:8000/api/v1/ap/invoices/ingest \
  -H "X-API-Key: test-key" \
  -F "file=@/tmp/invoice.xml")
echo $RESPONSE | jq .

# Extract invoice_id
INVOICE_ID=$(echo $RESPONSE | jq -r .invoice_id)
echo "Uploaded invoice ID: $INVOICE_ID"
```

### Postgres queries

```bash
# Connect
PGPASSWORD=uie_password psql -U uie_app -h localhost -d universal_invoice_engine

# Check invoices
SELECT id, filename, status, created_at FROM invoices ORDER BY created_at DESC;

# Inspect canonical data for one invoice
SELECT id, canonical_data FROM invoices LIMIT 1 \gx

# Exit
\q
```

---

## Summary

This demo showcases:
1. **Working software** (tests pass, API responds, endpoints work)
2. **Clean architecture** (clear separation of concerns)
3. **Real-world problem** (PEPPOL + SEPA, European AP automation)
4. **Thoughtful design** (idempotency, value objects, canonical storage)
5. **Testability** (comprehensive test suite)
6. **Roadmap clarity** (next steps and priorities)

**Total demo time:** ~25–30 minutes (including Q&A).

---

**Good luck with your CTO presentation!** 🚀
