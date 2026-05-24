from dataclasses import dataclass

from stdnum.iban import compact, is_valid


@dataclass(frozen=True, slots=True)
class IbanValidationResult:
    raw_input: str
    normalized_iban: str | None
    is_valid: bool
    error: str | None = None


def validate_iban(value: str) -> IbanValidationResult:
    cleaned = value.strip().replace(" ", "")
    if not cleaned:
        return IbanValidationResult(value, None, False, "IBAN is required")
    try:
        normalized = compact(cleaned)
    except Exception:
        return IbanValidationResult(value, None, False, "Invalid IBAN format")
    if not is_valid(normalized):
        return IbanValidationResult(value, normalized, False, "Invalid IBAN checksum")
    return IbanValidationResult(value, normalized, True, None)
