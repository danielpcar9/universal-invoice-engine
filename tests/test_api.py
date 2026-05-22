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
    assert "Maximum allowed size is 10MB" in response.json()["detail"]


XXE_PAYLOAD = """<?xml version="1.0"?><!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><Invoice>&xxe;</Invoice>"""


def test_xxe_blocked():
    files = {"file": ("xxe.xml", io.BytesIO(XXE_PAYLOAD.encode()), "text/xml")}
    response = client.post(
        "/api/v1/ap/invoices/ingest", files=files, headers=AUTH_HEADERS
    )
    assert response.status_code == 422
