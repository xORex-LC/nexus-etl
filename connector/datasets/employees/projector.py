from __future__ import annotations

from dataclasses import asdict

from connector.domain.models import Identity
from connector.domain.validation.row_rules import normalize_whitespace


def build_match_key(
    last_name: str | None,
    first_name: str | None,
    middle_name: str | None,
    personnel_number: str | None,
) -> str:
    """
    Назначение:
        Построить match_key для датасета employees.

    Контракт:
        На входе — сырые значения полей; на выходе — строка вида "last|first|middle|personnel".
    """
    parts = [
        normalize_whitespace(last_name) or "",
        normalize_whitespace(first_name) or "",
        normalize_whitespace(middle_name) or "",
        normalize_whitespace(personnel_number) or "",
    ]
    return "|".join(parts)

class EmployeesProjector:
    """
    Назначение:
        Проекция валидированной строки employees в desired_state/identity/source_ref.
    """

    def to_desired_state(self, validated_entity) -> dict:
        return asdict(validated_entity)

    def to_identity(self, validated_entity, validation_result) -> Identity:
        return Identity(
            primary="match_key",
            values={
                "match_key": validation_result.match_key,
                "usr_org_tab_num": validation_result.usr_org_tab_num or "",
            },
        )

    def to_source_ref(self, identity: Identity) -> dict:
        return {identity.primary: identity.primary_value}
