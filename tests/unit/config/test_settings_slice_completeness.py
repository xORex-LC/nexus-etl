from __future__ import annotations

from dataclasses import fields

from connector.config.app_settings import _SLICE_FIELD_MAP
from connector.config.config import Settings


def test_all_settings_fields_covered_by_slices():
    """Every field in Settings must appear in at least one slice mapping."""
    settings_fields = {f.name for f in fields(Settings)}
    mapped_fields: set[str] = set()
    for field_map in _SLICE_FIELD_MAP.values():
        mapped_fields.update(field_map.keys())

    unmapped = settings_fields - mapped_fields
    assert unmapped == set(), (
        f"Settings fields not mapped to any slice: {sorted(unmapped)}"
    )
