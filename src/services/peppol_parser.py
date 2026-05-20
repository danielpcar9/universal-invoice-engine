import logging
from decimal import Decimal
from typing import Optional

from lxml import etree  # type: ignore
from pydantic import BaseModel

logger = logging.getLogger("api")


class ParsedInvoice(BaseModel):
    """Canonical model for parsed invoice details (UBL 2.1/PEPPOL BIS 3.0 inspired)"""
    invoice_id: str
    issue_date: str
    due_date: Optional[str] = None
    currency: str
    supplier_name: str
    supplier_vat: Optional[str] = None
    customer_name: str
    customer_vat: Optional[str] = None
    total_amount: Decimal
    tax_amount: Decimal
    subtotal: Decimal


class PeppolParser:
    """High-speed XML parser tailored for PEPPOL BIS 3.0 (UBL 2.1) structures using lxml"""
    
    # Official PEPPOL / UBL 2.1 XML namespaces
    NAMESPACES = {
        "ubl": "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
        "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
        "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
    }

    @classmethod
    def parse(cls, xml_bytes: bytes) -> ParsedInvoice:
        """Parses raw PEPPOL XML bytes and extracts the canonical metadata.
        
        Args:
            xml_bytes: Raw byte payload of the XML file.
            
        Returns:
            ParsedInvoice: Canonical model containing the extracted invoice metadata.
            
        Raises:
            ValueError: If XML is malformed or lacks critical financial fields.
        """
        try:
            # 1. Instantiate the parser with security settings (disabled entity resolution to prevent XXE attacks)
            parser = etree.XMLParser(remove_blank_text=True, resolve_entities=False)
            tree = etree.fromstring(xml_bytes, parser=parser)
            
            # Helper inline function to extract clean text from xpath queries
            def xpath_text(query: str) -> str:
                nodes = tree.xpath(query, namespaces=cls.NAMESPACES)
                if nodes and len(nodes) > 0:
                    return str(nodes[0]).strip()
                return ""

            # 2. Extract Document Metadata
            invoice_id = xpath_text("//cbc:ID/text()")
            issue_date = xpath_text("//cbc:IssueDate/text()")
            due_date = xpath_text("//cbc:DueDate/text()")
            currency = xpath_text("//cbc:DocumentCurrencyCode/text()")

            # 3. Extract Accounting Supplier Details (AccountingSupplierParty)
            # Try Name node, fallback to Legal Registration Name
            supplier_name = xpath_text("//cac:AccountingSupplierParty/cac:Party/cac:PartyName/cbc:Name/text()") or \
                            xpath_text("//cac:AccountingSupplierParty/cac:Party/cac:PartyLegalEntity/cbc:RegistrationName/text()")
            supplier_vat = xpath_text("//cac:AccountingSupplierParty/cac:Party/cac:PartyTaxScheme/cbc:CompanyID/text()")

            # 4. Extract Accounting Customer Details (AccountingCustomerParty)
            customer_name = xpath_text("//cac:AccountingCustomerParty/cac:Party/cac:PartyName/cbc:Name/text()") or \
                            xpath_text("//cac:AccountingCustomerParty/cac:Party/cac:PartyLegalEntity/cbc:RegistrationName/text()")
            customer_vat = xpath_text("//cac:AccountingCustomerParty/cac:Party/cac:PartyTaxScheme/cbc:CompanyID/text()")

            # 5. Extract Monetary Totals (LegalMonetaryTotal)
            payable_str = xpath_text("//cac:LegalMonetaryTotal/cbc:PayableAmount/text()")
            tax_exclusive_str = xpath_text("//cac:LegalMonetaryTotal/cbc:TaxExclusiveAmount/text()")
            tax_inclusive_str = xpath_text("//cac:LegalMonetaryTotal/cbc:TaxInclusiveAmount/text()")

            # Conversion to Decimal for strict financial precision (avoid float representation issues)
            total_amount = Decimal(payable_str) if payable_str else Decimal("0.00")
            subtotal = Decimal(tax_exclusive_str) if tax_exclusive_str else Decimal("0.00")
            
            # Extract Tax amount directly, fallback to mathematical subtraction (Inclusive - Exclusive)
            tax_amount = Decimal("0.00")
            tax_amount_str = xpath_text("//cac:TaxTotal/cbc:TaxAmount/text()")
            if tax_amount_str:
                tax_amount = Decimal(tax_amount_str)
            elif tax_inclusive_str and tax_exclusive_str:
                tax_amount = Decimal(tax_inclusive_str) - Decimal(tax_exclusive_str)

            # 6. Strict validation on critical financial nodes
            if not invoice_id:
                raise ValueError("Missing critical Invoice ID (<cbc:ID>)")
            if not supplier_name:
                raise ValueError("Missing Accounting Supplier Name")
            if not customer_name:
                raise ValueError("Missing Accounting Customer Name")

            logger.info(f"Successfully parsed PEPPOL Invoice {invoice_id} from {supplier_name}")

            return ParsedInvoice(
                invoice_id=invoice_id,
                issue_date=issue_date,
                due_date=due_date if due_date else None,
                currency=currency if currency else "EUR",
                supplier_name=supplier_name,
                supplier_vat=supplier_vat if supplier_vat else None,
                customer_name=customer_name,
                customer_vat=customer_vat if customer_vat else None,
                total_amount=total_amount,
                tax_amount=tax_amount,
                subtotal=subtotal
            )

        except etree.XMLSyntaxError as e:
            logger.error(f"Malformed XML syntax error: {str(e)}")
            raise ValueError(f"Malformed XML payload: {str(e)}")
        except Exception as e:
            logger.error(f"Failure inside PEPPOL parsing engine: {str(e)}")
            raise ValueError(f"Failed to parse PEPPOL invoice: {str(e)}")
