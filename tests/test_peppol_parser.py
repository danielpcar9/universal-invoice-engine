from decimal import Decimal
import pytest
from src.services.ap.peppol_parser import PeppolParser

# Mock content for a valid PEPPOL BIS 3.0 (UBL 2.1) invoice XML
VALID_PEPPOL_XML = """<?xml version="1.0" encoding="UTF-8"?>
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

INVALID_PEPPOL_XML_MISSING_ID = """<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
         xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
    <cbc:IssueDate>2026-05-20</cbc:IssueDate>
    <cac:AccountingSupplierParty>
        <cac:Party>
            <cac:PartyName>
                <cbc:Name>Supplier Ltd</cbc:Name>
            </cac:PartyName>
        </cac:Party>
    </cac:AccountingSupplierParty>
</Invoice>
"""


def test_parse_valid_peppol_invoice():
    # Execute the parser
    parsed = PeppolParser.parse(VALID_PEPPOL_XML.encode("utf-8"))
    
    # Assertions
    assert parsed.invoice_id == "INV-2026-0001"
    assert parsed.issue_date == "2026-05-20"
    assert parsed.due_date == "2026-06-20"
    assert parsed.currency == "EUR"
    assert parsed.supplier_name == "Supplier Ltd"
    assert parsed.supplier_vat == "FR123456789"
    assert parsed.customer_name == "Customer Corp"
    assert parsed.customer_vat == "DE987654321"
    assert parsed.total_amount == Decimal("1200.00")
    assert parsed.subtotal == Decimal("1000.00")
    assert parsed.tax_amount == Decimal("200.00")  # (TaxInclusive - TaxExclusive)


def test_parse_missing_critical_fields_raises_value_error():
    with pytest.raises(ValueError, match="Missing critical Invoice ID"):
        PeppolParser.parse(INVALID_PEPPOL_XML_MISSING_ID.encode("utf-8"))


def test_parse_malformed_xml_raises_value_error():
    malformed_xml = "<Invoice><cbc:ID>123</cbc:ID>"  # Missing closing tag
    with pytest.raises(ValueError, match="Malformed XML payload"):
        PeppolParser.parse(malformed_xml.encode("utf-8"))
