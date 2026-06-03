from __future__ import annotations

from tests.support.dataset_artifacts import build_mapper, build_normalizer, controlled_source_record


def _normalized_org_path(**unit_levels: str) -> object:
    """Прогнать контролируемый mapper+normalizer и вернуть нормализованный org_path."""
    mapper = build_mapper()
    normalizer = build_normalizer()
    mapped = mapper.map(controlled_source_record(emp_id="1", **unit_levels))
    result = normalizer.normalize(mapped)
    assert result.errors == ()
    assert result.row is not None
    return result.row["org_path"]


def test_normalize_selects_last_non_empty_org_unit() -> None:
    """compact+last выбирает последнее непустое значение из multi-source списка
    (отвязано от живого employees YAML)."""
    assert _normalized_org_path(unit_l1="A", unit_l2="B", unit_l3="C") == "C"


def test_normalize_skips_trailing_empty_org_units() -> None:
    """Пустые хвостовые уровни игнорируются — берётся предыдущее непустое."""
    assert _normalized_org_path(unit_l1="A", unit_l2="B", unit_l3="") == "B"
