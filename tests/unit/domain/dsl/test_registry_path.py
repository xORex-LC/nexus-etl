from __future__ import annotations

from connector.common.runtime_paths import RuntimePathOverrides
from connector.domain.dsl.loader import configure_registry_path, configure_runtime_paths, datasets_root, load_registry, registry_path
from connector.domain.transform_dsl import load_source_spec_for_dataset


def test_configure_registry_path_changes_active_registry_without_rebinding_runtime_roots(tmp_path):
    runtime_root = tmp_path / "runtime"
    registry = tmp_path / "config" / "custom-registry.yaml"
    source = runtime_root / "etc" / "source-projection" / "custom" / "source.yaml"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(
        "dataset: custom\n"
        "source:\n"
        "  type: file\n"
        "  format: csv\n"
        "  location: /tmp/custom.csv\n",
        encoding="utf-8",
    )
    registry.parent.mkdir(parents=True, exist_ok=True)
    (runtime_root / "datasets").mkdir(parents=True, exist_ok=True)
    (runtime_root / "datasets" / "registry.yaml").write_text("datasets: {}\n", encoding="utf-8")
    registry.write_text(
        "datasets:\n"
        "  custom:\n"
        "    source: custom/source.yaml\n",
        encoding="utf-8",
    )

    try:
        configure_runtime_paths(RuntimePathOverrides(runtime_root=runtime_root))
        configure_registry_path(registry)

        assert registry_path() == registry.resolve()
        assert datasets_root() == (runtime_root / "datasets").resolve()
        assert "custom" in load_registry()["datasets"]

        spec = load_source_spec_for_dataset("custom")
        assert spec.dataset == "custom"
        assert spec.source.location == "/tmp/custom.csv"
    finally:
        configure_registry_path(None)
        configure_runtime_paths(None)
