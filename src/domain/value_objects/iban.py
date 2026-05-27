from dataclasses import dataclass

from src.services.ap.validation.rules.iban_validator import validate_iban


@dataclass(frozen=True)
class IBAN:
    value: str

    def __post_init__(self) -> None:
        result = validate_iban(self.value)

        if not result.is_valid:
            raise ValueError(
                f"Invalid IBAN: {result.error}"
            )

        normalized = result.normalized_iban or self.value

        object.__setattr__(
            self,
            "value",
            normalized,
        )

    def __str__(self) -> str:
        return self.value