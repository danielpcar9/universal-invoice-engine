from pathlib import Path

from src.services.ap.validation.compliance_scorer import (
    MAX_COMPLIANCE_SCORE,
    ComplianceScoreInput,
    score_compliance,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "peppol"
VALID_XML = (FIXTURES_DIR / "bis3_valid.xml").read_bytes()
INVALID_XML = b"<Invoice><cbc:ID>123</cbc:ID>"
VALID_IBAN = "DE89370400440532013000"
INVALID_IBAN = "DE89370400440532013001"


def _component_by_rule(result, rule: str):
    return next(c for c in result.breakdown if c.rule == rule)


def test_score_compliance_perfect_invoice():
    result = score_compliance(
        ComplianceScoreInput(
            xml_bytes=VALID_XML,
            iban=VALID_IBAN,
            is_duplicate=False,
        )
    )

    assert result.total_score == MAX_COMPLIANCE_SCORE
    assert result.max_score == 50
    assert _component_by_rule(result, "xsd_valid").passed is True
    assert _component_by_rule(result, "xsd_valid").points_awarded == 25
    assert _component_by_rule(result, "iban_valid").passed is True
    assert _component_by_rule(result, "iban_valid").points_awarded == 15
    assert _component_by_rule(result, "not_duplicate").passed is True
    assert _component_by_rule(result, "not_duplicate").points_awarded == 10


def test_score_compliance_duplicate_invoice():
    result = score_compliance(
        ComplianceScoreInput(
            xml_bytes=VALID_XML,
            iban=VALID_IBAN,
            is_duplicate=True,
        )
    )

    assert result.total_score == 40
    assert _component_by_rule(result, "not_duplicate").passed is False
    assert _component_by_rule(result, "not_duplicate").points_awarded == 0


def test_score_compliance_invalid_iban():
    result = score_compliance(
        ComplianceScoreInput(
            xml_bytes=VALID_XML,
            iban=INVALID_IBAN,
            is_duplicate=False,
        )
    )

    assert result.total_score == 35
    assert _component_by_rule(result, "iban_valid").passed is False
    assert _component_by_rule(result, "iban_valid").points_awarded == 0


def test_score_compliance_missing_iban():
    result = score_compliance(
        ComplianceScoreInput(
            xml_bytes=VALID_XML,
            iban=None,
            is_duplicate=False,
        )
    )

    assert result.total_score == 35
    assert _component_by_rule(result, "iban_valid").passed is False
    assert _component_by_rule(result, "iban_valid").detail == "IBAN is required for payment scoring"


def test_score_compliance_malformed_xml():
    result = score_compliance(
        ComplianceScoreInput(
            xml_bytes=INVALID_XML,
            iban=VALID_IBAN,
            is_duplicate=False,
        )
    )

    assert result.total_score == 25
    assert _component_by_rule(result, "xsd_valid").passed is False
    assert _component_by_rule(result, "xsd_valid").points_awarded == 0


def test_score_compliance_all_checks_fail():
    result = score_compliance(
        ComplianceScoreInput(
            xml_bytes=INVALID_XML,
            iban=INVALID_IBAN,
            is_duplicate=True,
        )
    )

    assert result.total_score == 0
    assert all(not component.passed for component in result.breakdown)
