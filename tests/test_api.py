import io
from fastapi.testclient import TestClient
from src.api.main import app



client = TestClient(app)

TEST_API_KEY = "test-api-key-placeholder"
AUTH_HEADERS = {"X-API-Key": TEST_API_KEY}

# Re-use the valid XML payload from parser tests
VALID_XML_CONTENT = """<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
         xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
    <cbc:ID>INV-2026-0001</cbc:ID>
    <cbc:IssueDate>2026-05-20</cbc:IssueDate>
    <cbc:DueDate>2026-06-20</cbc:DueDate>
    <cbc:DocumentCurrencyCode>EUR</cbc:DocumentCurrencyCode>
    
    <cac:AccountingSupplierParty>
        <cac:Party>
            <cac:PartyName>
                <cbc:Name>Supplier Ltd</cbc:Name>
            </cac:PartyName>
            <cac:PartyTaxScheme>
                <cbc:CompanyID>FR123456789</cbc:CompanyID>
                <cac:TaxScheme>
                    <cbc:ID>VAT</cbc:ID>
                </cac:TaxScheme>
            </cac:PartyTaxScheme>
        </cac:Party>
    </cac:AccountingSupplierParty>
    
    <cac:AccountingCustomerParty>
        <cac:Party>
            <cac:PartyName>
                <cbc:Name>Customer Corp</cbc:Name>
            </cac:PartyName>
            <cac:PartyTaxScheme>
                <cbc:CompanyID>DE987654321</cbc:CompanyID>
                <cac:TaxScheme>
                    <cbc:ID>VAT</cbc:ID>
                </cac:TaxScheme>
            </cac:PartyTaxScheme>
        </cac:Party>
    </cac:AccountingCustomerParty>
    
    <cac:LegalMonetaryTotal>
        <cbc:LineExtensionAmount currencyID="EUR">1000.00</cbc:LineExtensionAmount>
        <cbc:TaxExclusiveAmount currencyID="EUR">1000.00</cbc:TaxExclusiveAmount>
        <cbc:TaxInclusiveAmount currencyID="EUR">1200.00</cbc:TaxInclusiveAmount>
        <cbc:PayableAmount currencyID="EUR">1200.00</cbc:PayableAmount>
    </cac:LegalMonetaryTotal>
</Invoice>
"""

MALFORMED_XML_CONTENT = "<Invoice><cbc:ID>123</cbc:ID>"


def _invoice_upload_files() -> dict:
    return {
        "file": (
            "invoice.xml",
            io.BytesIO(VALID_XML_CONTENT.encode("utf-8")),
            "text/xml",
        )
    }


def test_health_check():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ingest_valid_xml():
    files = {"file": ("invoice.xml", io.BytesIO(VALID_XML_CONTENT.encode("utf-8")), "text/xml")}
    response = client.post(
        "/api/v1/ap/invoices/ingest", files=files, headers=AUTH_HEADERS
    )

    assert response.status_code == 201
    data = response.json()
    assert "invoice_id" in data
    assert data["filename"] == "invoice.xml"
    assert data["status"] == "received"
    assert "content_hash" in data
    assert len(data["content_hash"]) == 64
    assert "parsed_invoice" in data

    parsed = data["parsed_invoice"]
    assert parsed["invoice_id"] == "INV-2026-0001"
    assert parsed["supplier_name"] == "Supplier Ltd"
    assert parsed["customer_name"] == "Customer Corp"
    assert parsed["total_amount"] == "1200.00"
    assert parsed["subtotal"] == "1000.00"
    assert parsed["tax_amount"] == "200.00"


def test_ingest_duplicate_xml_returns_409():
    first_response = client.post(
        "/api/v1/ap/invoices/ingest", files=_invoice_upload_files(), headers=AUTH_HEADERS
    )
    assert first_response.status_code == 201
    first_invoice_id = first_response.json()["invoice_id"]
    content_hash = first_response.json()["content_hash"]

    duplicate_response = client.post(
        "/api/v1/ap/invoices/ingest", files=_invoice_upload_files(), headers=AUTH_HEADERS
    )
    assert duplicate_response.status_code == 409
    detail = duplicate_response.json()
    assert detail["detail"] == "Invoice already ingested"
    assert detail["raw_hash"] == content_hash
    assert detail["existing_invoice_id"] == first_invoice_id


def test_ingest_malformed_xml():
    files = {"file": ("invoice.xml", io.BytesIO(MALFORMED_XML_CONTENT.encode("utf-8")), "text/xml")}
    response = client.post(
        "/api/v1/ap/invoices/ingest", files=files, headers=AUTH_HEADERS
    )
    
    assert response.status_code == 422
    assert "XML invoice parsing failed" in response.json()["detail"]


def test_ingest_unsupported_extension():
    files = {"file": ("invoice.txt", io.BytesIO(b"dummy plain text"), "text/plain")}
    response = client.post(
        "/api/v1/ap/invoices/ingest", files=files, headers=AUTH_HEADERS
    )
    
    assert response.status_code == 415
    assert "Unsupported format" in response.json()["detail"]


def test_ingest_payload_too_large():
    # Max size is 10MB. We send 11MB
    large_payload = b"A" * (11 * 1024 * 1024)
    files = {"file": ("invoice.pdf", io.BytesIO(large_payload), "application/pdf")}
    response = client.post(
        "/api/v1/ap/invoices/ingest", files=files, headers=AUTH_HEADERS
    )
    
    assert response.status_code == 413
    assert "10MB" in response.json()["detail"]


XXE_PAYLOAD = """<?xml version="1.0"?><!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><Invoice>&xxe;</Invoice>"""


def test_xxe_blocked():
    files = {"file": ("xxe.xml", io.BytesIO(XXE_PAYLOAD.encode()), "text/xml")}
    response = client.post(
        "/api/v1/ap/invoices/ingest", files=files, headers=AUTH_HEADERS
    )
    assert response.status_code == 422




def test_sepa_generate_from_invoice_id():
    # 1. Ingest a valid XML with PaymentMeans
    xml_with_payment = """<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
         xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:ID>SEP-INV-001</cbc:ID>
  <cbc:IssueDate>2026-05-20</cbc:IssueDate>
  <cbc:DocumentCurrencyCode>EUR</cbc:DocumentCurrencyCode>
  <cac:AccountingSupplierParty>
    <cac:Party>
      <cac:PartyName><cbc:Name>Acme Supplies</cbc:Name></cac:PartyName>
      <cac:PartyTaxScheme><cbc:CompanyID>ESB1234567</cbc:CompanyID></cac:PartyTaxScheme>
    </cac:Party>
  </cac:AccountingSupplierParty>
  <cac:AccountingCustomerParty>
    <cac:Party>
      <cac:PartyName><cbc:Name>My Company</cbc:Name></cac:PartyName>
    </cac:Party>
  </cac:AccountingCustomerParty>
  <cac:PaymentMeans>
    <cbc:PaymentMeansCode>58</cbc:PaymentMeansCode>
    <cac:PayeeFinancialAccount>
      <cbc:ID schemeID="IBAN">ES9121000418450200051332</cbc:ID>
      <cac:FinancialInstitutionBranch>
        <cac:FinancialInstitution>
          <cbc:ID schemeID="BIC">CAIXESBB</cbc:ID>
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
"""

    files = {
        "file": ("sepa_invoice.xml", io.BytesIO(xml_with_payment.encode("utf-8")), "text/xml")
    }
    ingest_response = client.post(
        "/api/v1/ap/invoices/ingest", files=files, headers=AUTH_HEADERS
    )
    assert ingest_response.status_code == 201
    invoice_id = ingest_response.json()["invoice_id"]
    parsed = ingest_response.json()["parsed_invoice"]
    assert parsed["creditor_iban"] == "ES9121000418450200051332"
    assert parsed["creditor_bic"] == "CAIXESBB"

    # 2. Generate SEPA from that invoice
    payload = {
        "invoice_id": invoice_id,
        "debtor_name": "My Company S.L.",
        "debtor_iban": "ES7921000813610123456789",
        "debtor_bic": "BBVAESMM",
        "requested_execution_date": "2026-05-25",
    }
    sepa_response = client.post(
        "/api/v1/ap/payments/sepa/generate",
        json=payload,
        headers=AUTH_HEADERS,
    )
    assert sepa_response.status_code == 201
    data = sepa_response.json()
    assert data["invoice_id"] == invoice_id
    assert data["amount"] == "121.00"
    assert data["currency"] == "EUR"
    assert data["creditor_iban"] == "ES9121000418450200051332"

    # 3. Basic XML structure validation of the generated payload
    xml_payload = data["xml_payload"]
    assert "pain.001.001.03" in xml_payload
    assert "<MsgId>" in xml_payload
    assert "<CtrlSum>121.00</CtrlSum>" in xml_payload
    assert "<InstdAmt Ccy=\"EUR\">121.00</InstdAmt>" in xml_payload
    assert "ES9121000418450200051332" in xml_payload  # Creditor IBAN
    assert "CAIXESBB" in xml_payload  # Creditor BIC
    assert "ES7921000813610123456789" in xml_payload  # Debtor IBAN


def test_sepa_generate_missing_creditor_iban():
    # Invoice without PaymentMeans -> no creditor_iban
    xml_no_payment = """<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
         xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:ID>NO-PAY-001</cbc:ID>
  <cbc:IssueDate>2026-05-20</cbc:IssueDate>
  <cbc:DocumentCurrencyCode>EUR</cbc:DocumentCurrencyCode>
  <cac:AccountingSupplierParty>
    <cac:Party>
      <cac:PartyName><cbc:Name>No Bank Supplier</cbc:Name></cac:PartyName>
    </cac:Party>
  </cac:AccountingSupplierParty>
  <cac:AccountingCustomerParty>
    <cac:Party>
      <cac:PartyName><cbc:Name>My Company</cbc:Name></cac:PartyName>
    </cac:Party>
  </cac:AccountingCustomerParty>
  <cac:LegalMonetaryTotal>
    <cbc:PayableAmount currencyID="EUR">50.00</cbc:PayableAmount>
  </cac:LegalMonetaryTotal>
</Invoice>
"""

    files = {
        "file": ("no_bank.xml", io.BytesIO(xml_no_payment.encode("utf-8")), "text/xml")
    }
    ingest = client.post(
        "/api/v1/ap/invoices/ingest", files=files, headers=AUTH_HEADERS
    )
    assert ingest.status_code == 201
    invoice_id = ingest.json()["invoice_id"]
    assert ingest.json()["parsed_invoice"]["creditor_iban"] is None

    payload = {
        "invoice_id": invoice_id,
        "debtor_name": "My Company",
        "debtor_iban": "ES7921000813610123456789",
    }
    sepa = client.post(
        "/api/v1/ap/payments/sepa/generate",
        json=payload,
        headers=AUTH_HEADERS,
    )
    assert sepa.status_code == 422
    assert "missing creditor_iban" in sepa.json()["detail"]


def test_sepa_generate_invoice_not_found():
    payload = {
        "invoice_id": "00000000-0000-0000-0000-000000000000",
        "debtor_name": "My Company",
        "debtor_iban": "ES7921000813610123456789",
    }
    response = client.post(
        "/api/v1/ap/payments/sepa/generate",
        json=payload,
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


def test_unhandled_exception_remains_generic_always():
    from src.api.dependencies.auth import verify_api_key
    from fastapi.testclient import TestClient

    local_client = TestClient(app, raise_server_exceptions=False)

    def mock_verify_api_key():
        raise RuntimeError("Generic DB/logic failure")

    payload = {
        "invoice_id": "00000000-0000-0000-0000-000000000000",
        "debtor_name": "My Company",
        "debtor_iban": "ES7921000813610123456789",
    }

    # 1. In standard/production-like execution, return general 500 without traceback
    app.dependency_overrides[verify_api_key] = mock_verify_api_key
    try:
        response = local_client.post(
            "/api/v1/ap/payments/sepa/generate",
            json=payload,
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 500
        assert response.json() == {"detail": "An unexpected error occurred in the server."}
    finally:
        app.dependency_overrides.clear()

    # 2. Even in debug mode (DEBUG=1), the response MUST remain generic and NOT leak internal stack traces
    app.dependency_overrides[verify_api_key] = mock_verify_api_key
    from unittest.mock import patch
    try:
        with patch.dict("os.environ", {"DEBUG": "1"}):
            response = local_client.post(
                "/api/v1/ap/payments/sepa/generate",
                json=payload,
                headers=AUTH_HEADERS,
            )
            assert response.status_code == 500
            assert response.json() == {"detail": "An unexpected error occurred in the server."}
    finally:
        app.dependency_overrides.clear()