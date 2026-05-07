from __future__ import annotations

from pathlib import Path


LEGACY_MARKERS = (
    "registry" + ".yml",
    "location" + "_ref",
    "EMPLOYEES" + "_SOURCE_PATH",
    "../" + "dictionaries",
    "./" + "cache",
    "./" + "logs",
    "./" + "reports",
)

GUARDED_PATHS = (
    Path("connector/common/runtime_paths.py"),
    Path("connector/domain/dsl/loader/_common.py"),
    Path("connector/config/models.py"),
    Path("datasets/registry.yaml"),
    Path("datasets/yaml_templates"),
    Path("datasets/dictionaries"),
    Path("examples/configs"),
)


def _iter_guarded_files(repo_root: Path) -> list[Path]:
    files: list[Path] = []
    for relative_path in GUARDED_PATHS:
        path = repo_root / relative_path
        if path.is_file():
            files.append(path)
            continue
        files.extend(
            candidate
            for candidate in path.rglob("*")
            if candidate.is_file() and candidate.suffix in {".py", ".yaml", ".yml", ".md"}
        )
    return files


def test_runtime_migration_guard_has_no_removed_legacy_markers() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    checked_files = _iter_guarded_files(repo_root)

    hits: list[str] = []
    for file_path in checked_files:
        text = file_path.read_text(encoding="utf-8")
        for marker in LEGACY_MARKERS:
            if marker in text:
                hits.append(f"{file_path.relative_to(repo_root)} -> {marker}")

    assert hits == []
