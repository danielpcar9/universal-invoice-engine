import io

import pytest
from fastapi import UploadFile

from src.db.session import AsyncSessionLocal
from src.repositories.invoice_repository import (
    DuplicateInvoiceError as RepoDuplicateInvoiceError,
)
from src.repositories.sql_invoice_repository import SqlInvoiceRepository
from src.services.invoice_service import (
    DuplicateInvoiceError,
    FileTooLargeError,
    InvoiceService,
    InvalidInvoiceError,
    UnsupportedFormatError,
)
from src.services.sepa_payment_service import (
    MissingIbanError,
    SepaPaymentService,
)


@pytest.fixture
async def service():
    async with AsyncSessionLocal() as session:
        repository = SqlInvoiceRepository(session)
        yield InvoiceService(repository)


@pytest.fixture
async def sepa_service():
    async with AsyncSessionLocal() as session:
        repository = SqlInvoiceRepository(session)
        yield SepaPaymentService(repository)


def _valid_xml_upload(filename: str = "test.xml") -> UploadFile:
    return UploadFile(
        filename=filename,
        file=io.BytesIO(b"""<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
         xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:ID>INV-TEST-001</cbc:ID>
  <cbc:IssueDate>2026-05-20</cbc:IssueDate>
  <cbc:DocumentCurrencyCode>EUR</cbc:DocumentCurrencyCode>
  <cac:AccountingSupplierParty>
    <cac:Party>
      <cac:PartyName><cbc:Name>Test Supplier</cbc:Name></cac:PartyName>
    </cac:Party>
  </cac:AccountingSupplierParty>
  <cac:AccountingCustomerParty>
    <cac:Party>
      <cac:PartyName><cbc:Name>Test Customer</cbc:Name></cac:PartyName>
    </cac:Party>
  </cac:AccountingCustomerParty>
  <cac:PaymentMeans>
    <cac:PayeeFinancialAccount>
      <cbc:ID schemeID="IBAN">FR1420041010050500013M02606</cbc:ID>
    </cac:PayeeFinancialAccount>
  </cac:PaymentMeans>
  <cac:LegalMonetaryTotal>
    <cbc:PayableAmount currencyID="EUR">100.00</cbc:PayableAmount>
  </cac:LegalMonetaryTotal>
</Invoice>
"""),
    )


@pytest.mark.asyncio
async def test_ingest_valid_xml(service: InvoiceService):
    result = await service.ingest(_valid_xml_upload())

    assert result.filename == "test.xml"
    assert result.status == "received"
    assert result.parsed_invoice is not None
    assert result.parsed_invoice.invoice_id == "INV-TEST-001"
    assert result.parsed_invoice.creditor_iban == "FR1420041010050500013M02606"


@pytest.mark.asyncio
async def test_ingest_unsupported_format(service: InvoiceService):
    file = UploadFile(filename="test.txt", file=io.BytesIO(b"plain text"))
    with pytest.raises(UnsupportedFormatError):
        await service.ingest(file)


@pytest.mark.asyncio
async def test_ingest_file_too_large(service: InvoiceService):
    large_content = b"A" * (11 * 1024 * 1024)
    file = UploadFile(filename="large.pdf", file=io.BytesIO(large_content))
    with pytest.raises(FileTooLargeError):
        await service.ingest(file)


@pytest.mark.asyncio
async def test_ingest_malformed_xml(service: InvoiceService):
    file = UploadFile(filename="bad.xml", file=io.BytesIO(b"not xml"))
    with pytest.raises(InvalidInvoiceError):
        await service.ingest(file)


@pytest.mark.asyncio
async def test_ingest_translates_repository_duplicate_error():
    existing_invoice_id = "existing-invoice-id"

    class DuplicateRepository:
        async def insert_invoice(
            self,
            *,
            raw_hash: str,
            filename: str,
            source_format: str,
            canonical_data,
        ):
            raise RepoDuplicateInvoiceError(raw_hash, existing_invoice_id)

        async def get_by_id(self, *, invoice_id: str):
            return None

    service = InvoiceService(DuplicateRepository())

    with pytest.raises(DuplicateInvoiceError) as exc_info:
        await service.ingest(_valid_xml_upload())

    assert len(exc_info.value.raw_hash) == 64
    assert exc_info.value.existing_invoice_id == existing_invoice_id


@pytest.mark.asyncio
async def test_generate_sepa_missing_iban(service: InvoiceService, sepa_service: SepaPaymentService):
    # First ingest invoice without PaymentMeans
    file = UploadFile(
        filename="no_iban.xml",
        file=io.BytesIO(b"""<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
         xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:ID>NO-IBAN-001</cbc:ID>
  <cbc:IssueDate>2026-05-20</cbc:IssueDate>
  <cbc:DocumentCurrencyCode>EUR</cbc:DocumentCurrencyCode>
  <cac:AccountingSupplierParty>
    <cac:Party>
      <cac:PartyName><cbc:Name>No Bank</cbc:Name></cac:PartyName>
    </cac:Party>
  </cac:AccountingSupplierParty>
  <cac:AccountingCustomerParty>
    <cac:Party>
      <cac:PartyName><cbc:Name>Customer</cbc:Name></cac:PartyName>
    </cac:Party>
  </cac:AccountingCustomerParty>
  <cac:LegalMonetaryTotal>
    <cbc:PayableAmount currencyID="EUR">50.00</cbc:PayableAmount>
  </cac:LegalMonetaryTotal>
</Invoice>
"""),
    )

    result = await service.ingest(file)
    invoice_id = result.invoice_id

    with pytest.raises(MissingIbanError, match="missing creditor_iban"):
        await sepa_service.generate_sepa(
            invoice_id=invoice_id,
            debtor_name="MyCo",
            debtor_iban="ES7921000813610123456789",
        )
