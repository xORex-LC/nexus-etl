from __future__ import annotations

from pathlib import Path

from connector.common.runtime_paths import RuntimePaths
from connector.domain.dsl.loader import datasets_root, registry_path
from connector.domain.dsl.loader import _common as common_loader


def test_dsl_loader_uses_runtime_paths_default_registry(tmp_path: Path, monkeypatch) -> None:
    runtime_root = tmp_path / "runtime"
    datasets_dir = runtime_root / "datasets"
    registry = datasets_dir / "registry.yaml"
    datasets_dir.mkdir(parents=True, exist_ok=True)
    registry.write_text("datasets: {}\n", encoding="utf-8")

    monkeypatch.setattr(
        common_loader,
        "get_runtime_paths",
        lambda: RuntimePaths(
            root=runtime_root.resolve(),
            config_root=(runtime_root / "etc").resolve(),
            datasets_root=datasets_dir.resolve(),
            dictionary_specs_root=(runtime_root / "etc" / "dictionaries").resolve(),
            dictionary_data_root=(runtime_root / "dictionaries").resolve(),
            source_projection_root=(runtime_root / "etc" / "source-projection").resolve(),
            target_projection_root=(runtime_root / "etc" / "target-projection").resolve(),
            default_registry_path=registry.resolve(),
            cache_root=(runtime_root / "var" / "cache").resolve(),
            logs_root=(runtime_root / "var" / "logs").resolve(),
            reports_root=(runtime_root / "var" / "reports").resolve(),
        ),
    )
    common_loader._repo_root.cache_clear()
    common_loader._load_registry_or_raise.cache_clear()
    try:
        assert registry_path() == registry.resolve()
        assert datasets_root() == datasets_dir.resolve()
    finally:
        common_loader._repo_root.cache_clear()
        common_loader._load_registry_or_raise.cache_clear()
