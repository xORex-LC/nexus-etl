from __future__ import annotations

from connector.domain.dsl.loader import configure_registry_path, datasets_root, load_registry, registry_path
from connector.domain.transform_dsl import load_source_spec_for_dataset


def test_configure_registry_path_changes_active_registry_and_datasets_root(tmp_path):
    registry = tmp_path / "custom-registry.yaml"
    source = tmp_path / "source.yaml"
    source.write_text(
        "dataset: custom\n"
        "source:\n"
        "  type: file\n"
        "  format: csv\n"
        "  location: /tmp/custom.csv\n",
        encoding="utf-8",
    )
    registry.write_text(
        "datasets:\n"
        "  custom:\n"
        "    source: source.yaml\n",
        encoding="utf-8",
    )

    try:
        configure_registry_path(registry)

        assert registry_path() == registry.resolve()
        assert datasets_root() == tmp_path.resolve()
        assert "custom" in load_registry()["datasets"]

        spec = load_source_spec_for_dataset("custom")
        assert spec.dataset == "custom"
        assert spec.source.location == "/tmp/custom.csv"
    finally:
        configure_registry_path(None)
