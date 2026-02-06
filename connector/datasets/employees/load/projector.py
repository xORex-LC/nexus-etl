from __future__ import annotations

from dataclasses import asdict

from connector.domain.models import Identity

class EmployeesProjector:
    """
    Назначение:
        Проекция строки employees в desired_state/identity/source_ref.
    """

    def to_desired_state(self, entity) -> dict:
        desired = asdict(entity)
        desired.pop("password", None)
        desired.pop("target_id", None)
        return desired

    def to_identity(self, entity, match_context) -> Identity:
        _ = entity
        return Identity(
            primary="match_key",
            values={
                "match_key": match_context.match_key,
                "usr_org_tab_num": match_context.usr_org_tab_num or "",
            },
        )

    def to_source_ref(self, identity: Identity) -> dict:
        return {identity.primary: identity.primary_value}
