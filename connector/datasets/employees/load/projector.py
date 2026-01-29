from __future__ import annotations

from dataclasses import asdict

from connector.domain.models import Identity

class EmployeesProjector:
    """
    Назначение:
        Проекция валидированной строки employees в desired_state/identity/source_ref.
    """

    def to_desired_state(self, validated_entity) -> dict:
        desired = asdict(validated_entity)
        desired.pop("password", None)
        desired.pop("target_id", None)
        return desired

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
