from dataclasses import dataclass

from lxml import etree  # type: ignore

from src.services.ap.peppol_parser import PeppolParser
from src.services.ap.validation.rules.iban_validator import validate_iban

# TODO(schematron): EN16931 business rules — replace/extend xsd_valid weight
# TODO(vies): async VAT ID verification — additional score component

POINTS_XSD_VALID = 25
POINTS_IBAN_VALID = 15
POINTS_NOT_DUPLICATE = 10
MAX_COMPLIANCE_SCORE = POINTS_XSD_VALID + POINTS_IBAN_VALID + POINTS_NOT_DUPLICATE

UBL_INVOICE_NAMESPACE = PeppolParser.NAMESPACES["ubl"]


@dataclass(frozen=True, slots=True)
class ComplianceScoreInput:
    xml_bytes: bytes | None = None
    iban: str | None = None
    is_duplicate: bool = False


@dataclass(frozen=True, slots=True)
class ScoreComponent:
    rule: str
    points_awarded: int
    max_points: int
    passed: bool
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class ComplianceScoreResult:
    total_score: int
    max_score: int
    breakdown: tuple[ScoreComponent, ...]


def _is_xsd_valid_mvp(xml_bytes: bytes) -> tuple[bool, str | None]:
    try:
        parser = etree.XMLParser(
            remove_blank_text=True,
            resolve_entities=False,
            no_network=True,
            load_dtd=False,
            huge_tree=False,
        )
        root = etree.fromstring(xml_bytes, parser=parser)
    except etree.XMLSyntaxError as exc:
        return False, f"Malformed XML: {exc}"

    local_name = etree.QName(root).localname
    if local_name != "Invoice":
        return False, f"Expected root element Invoice, got {local_name}"

    if root.tag != f"{{{UBL_INVOICE_NAMESPACE}}}Invoice":
        return False, "Root element is not in the UBL Invoice namespace"

    return True, None


def score_compliance(input_data: ComplianceScoreInput) -> ComplianceScoreResult:
    breakdown: list[ScoreComponent] = []

    if input_data.xml_bytes is not None:
        xsd_passed, xsd_detail = _is_xsd_valid_mvp(input_data.xml_bytes)
    else:
        xsd_passed, xsd_detail = False, "No XML payload provided"

    breakdown.append(
        ScoreComponent(
            rule="xsd_valid",
            points_awarded=POINTS_XSD_VALID if xsd_passed else 0,
            max_points=POINTS_XSD_VALID,
            passed=xsd_passed,
            detail=xsd_detail,
        )
    )

    iban_value = (input_data.iban or "").strip()
    if iban_value:
        iban_result = validate_iban(iban_value)
        iban_passed = iban_result.is_valid
        iban_detail = iban_result.error
    else:
        iban_passed = False
        iban_detail = "IBAN is required for payment scoring"

    breakdown.append(
        ScoreComponent(
            rule="iban_valid",
            points_awarded=POINTS_IBAN_VALID if iban_passed else 0,
            max_points=POINTS_IBAN_VALID,
            passed=iban_passed,
            detail=iban_detail,
        )
    )

    not_duplicate_passed = not input_data.is_duplicate
    breakdown.append(
        ScoreComponent(
            rule="not_duplicate",
            points_awarded=POINTS_NOT_DUPLICATE if not_duplicate_passed else 0,
            max_points=POINTS_NOT_DUPLICATE,
            passed=not_duplicate_passed,
            detail="Invoice is a duplicate" if input_data.is_duplicate else None,
        )
    )

    total_score = sum(component.points_awarded for component in breakdown)
    return ComplianceScoreResult(
        total_score=total_score,
        max_score=MAX_COMPLIANCE_SCORE,
        breakdown=tuple(breakdown),
    )
