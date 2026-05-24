import pytest

from src.services.ap.validation.rules.iban_validator import validate_iban


@pytest.mark.parametrize(
    ("iban", "expected_normalized"),
    [
        ("DE89370400440532013000", "DE89370400440532013000"),
        ("FR1420041010050500013M02606", "FR1420041010050500013M02606"),
        ("IE29AIBK93115212345678", "IE29AIBK93115212345678"),
        ("DE89 3704 0044 0532 0130 00", "DE89370400440532013000"),
    ],
)
def test_validate_iban_accepts_valid_ibans(iban: str, expected_normalized: str) -> None:
    result = validate_iban(iban)

    assert result.is_valid is True
    assert result.normalized_iban == expected_normalized
    assert result.error is None


def test_validate_iban_rejects_invalid_checksum() -> None:
    result = validate_iban("DE89370400440532013001")

    assert result.is_valid is False
    assert result.normalized_iban == "DE89370400440532013001"
    assert result.error == "Invalid IBAN checksum"


def test_validate_iban_rejects_empty_input() -> None:
    result = validate_iban("")

    assert result.is_valid is False
    assert result.normalized_iban is None
    assert result.error == "IBAN is required"
