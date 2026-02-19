"""
Назначение:
    Compile-policy опции Cache DSL.
"""

from __future__ import annotations

from dataclasses import dataclass

from connector.domain.dsl.build_options import BaseDslBuildOptions


@dataclass(frozen=True)
class CacheDslBuildOptions(BaseDslBuildOptions):
    """
    Назначение:
        Compile-policy опции cache DSL компиляции.
    """

    require_sync_dataset_match: bool = True
    fail_on_unknown_dependencies: bool = True
    fail_on_unknown_pk_fields: bool = True
    fail_on_unknown_index_fields: bool = True
    fail_on_duplicate_projection_targets: bool = True
    fail_on_unknown_projection_targets: bool = True
    forbid_is_deleted_and_soft_delete_together: bool = True
