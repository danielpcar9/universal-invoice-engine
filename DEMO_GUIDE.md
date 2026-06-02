# Demo Guide

This is a short walkthrough for presenting Universal Invoice Engine as a focused backend portfolio project.

Target duration: 5-8 minutes.

## 1. One-Sentence Pitch

Universal Invoice Engine is a backend engine for European accounts payable automation: it ingests PEPPOL invoices, stores canonical invoice data idempotently, and generates SEPA payment XML.

## 2. Pre-Demo Checks

```bash
docker-compose up -d postgres
uv run alembic upgrade head
uv run ruff check .
uv run pytest
uv run alembic check
```

Expected:

```text
All checks passed.
32 tests passed.
No new upgrade operations detected.
```

Start the API:

```bash
uv run uvicorn src.api.main:app --reload
```

## 3. Explain The Architecture

Use this mental model:

```text
API -> Services -> Domain/Ports -> Repository -> PostgreSQL
          |              |
          |              +-> IBAN validation
          +-> PEPPOL parser / SEPA generator
```

Key points:

- routers are thin HTTP boundaries
- services orchestrate use cases
- repository protocol keeps services away from SQLAlchemy details
- PostgreSQL enforces duplicate protection through `raw_hash`
- Alembic owns schema versioning

## 4. Health Check

```bash
curl http://127.0.0.1:8000/api/v1/health
```

Expected:

```json
{"status":"ok"}
```

## 5. Create A Demo Invoice

This sample includes creditor IBAN data, so it can be used for both ingestion and SEPA generation.

```bash
cat > /tmp/invoice.xml << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
         xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:ID>DEMO-INV-001</cbc:ID>
  <cbc:IssueDate>2026-06-01</cbc:IssueDate>
  <cbc:DocumentCurrencyCode>EUR</cbc:DocumentCurrencyCode>

  <cac:AccountingSupplierParty>
    <cac:Party>
      <cac:PartyName><cbc:Name>Acme Supplies GmbH</cbc:Name></cac:PartyName>
      <cac:PartyTaxScheme><cbc:CompanyID>DE123456789</cbc:CompanyID></cac:PartyTaxScheme>
    </cac:Party>
  </cac:AccountingSupplierParty>

  <cac:AccountingCustomerParty>
    <cac:Party>
      <cac:PartyName><cbc:Name>My Company S.L.</cbc:Name></cac:PartyName>
      <cac:PartyTaxScheme><cbc:CompanyID>ESB12345678</cbc:CompanyID></cac:PartyTaxScheme>
    </cac:Party>
  </cac:AccountingCustomerParty>

  <cac:PaymentMeans>
    <cac:PayeeFinancialAccount>
      <cbc:ID schemeID="IBAN">DE89370400440532013000</cbc:ID>
      <cac:FinancialInstitutionBranch>
        <cac:FinancialInstitution>
          <cbc:ID schemeID="BIC">COBADEFFXXX</cbc:ID>
        </cac:FinancialInstitution>
      </cac:FinancialInstitutionBranch>
    </cac:PayeeFinancialAccount>
  </cac:PaymentMeans>

  <cac:TaxTotal>
    <cbc:TaxAmount currencyID="EUR">21.00</cbc:TaxAmount>
  </cac:TaxTotal>

  <cac:LegalMonetaryTotal>
    <cbc:TaxExclusiveAmount currencyID="EUR">100.00</cbc:TaxExclusiveAmount>
    <cbc:TaxInclusiveAmount currencyID="EUR">121.00</cbc:TaxInclusiveAmount>
    <cbc:PayableAmount currencyID="EUR">121.00</cbc:PayableAmount>
  </cac:LegalMonetaryTotal>
</Invoice>
EOF
```

## 6. Ingest The Invoice

```bash
RESPONSE=$(curl -s -X POST http://127.0.0.1:8000/api/v1/ap/invoices/ingest \
  -H "X-API-Key: demo-api-key" \
  -F "file=@/tmp/invoice.xml")

echo "$RESPONSE" | jq .
INVOICE_ID=$(echo "$RESPONSE" | jq -r .invoice_id)
echo "$INVOICE_ID"
```

Expected:

- HTTP `201 Created`
- response includes `invoice_id`
- response includes `content_hash`
- `parsed_invoice.creditor_iban` is present
- `parsed_invoice.total_amount` is `"121.00"`

Talking point:

> The system converts a PEPPOL XML document into canonical invoice data and stores it with a database-backed idempotency key.

## 7. Demonstrate Idempotency

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/ap/invoices/ingest \
  -H "X-API-Key: demo-api-key" \
  -F "file=@/tmp/invoice.xml" | jq .
```

Expected:

```json
{
  "detail": "Invoice already ingested",
  "raw_hash": "...",
  "existing_invoice_id": "..."
}
```

Talking point:

> Duplicate protection is enforced by PostgreSQL through the unique `raw_hash` index, so it remains safe even if multiple API instances exist.

## 8. Generate SEPA XML

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/ap/payments/sepa/generate \
  -H "X-API-Key: demo-api-key" \
  -H "Content-Type: application/json" \
  -d "{
    \"invoice_id\": \"$INVOICE_ID\",
    \"debtor_name\": \"My Company S.L.\",
    \"debtor_iban\": \"ES7921000813610123456789\",
    \"debtor_bic\": \"BBVAESMM\",
    \"requested_execution_date\": \"2026-06-15\"
  }" | jq .
```

Expected:

- HTTP `201 Created`
- response includes `payment_id`
- response includes `xml_payload`
- `xml_payload` contains `pain.001.001.03`
- amount is `"121.00"`
- creditor IBAN is `"DE89370400440532013000"`

Talking point:

> The system turns validated invoice data into an ISO 20022 SEPA credit transfer payload.

## 9. Show The Database

```bash
PGPASSWORD=uie_password psql -U uie_app -h localhost -d universal_invoice_engine
```

Useful queries:

```sql
SELECT id, filename, status, raw_hash FROM invoices ORDER BY created_at DESC LIMIT 5;
SELECT id, canonical_data FROM invoices ORDER BY created_at DESC LIMIT 1;
```

Talking point:

> The database stores a canonical JSONB payload and enforces uniqueness at the persistence boundary.

## 10. Defend The Tradeoffs

Use this concise answer:

> I kept it as a modular monolith because this is an MVP backend engine, not a full SaaS platform. The important boundaries are still clear: API, services, domain ports, repository adapter, and database. I would move parsing to background jobs and add audit/workflow states before trying to split this into microservices.

## 11. What Is Deliberately Not Implemented

- dashboard
- full ERP/accounting flows
- tenant model
- OCR pipeline
- production API key management
- full EN16931/Schematron validation

These are valid production evolutions, but they are outside the scope of this focused backend engine.
