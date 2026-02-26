from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[3]


def _python_files(*relative_dirs: str) -> list[Path]:
    files: list[Path] = []
    for rel_dir in relative_dirs:
        base = ROOT / rel_dir
        files.extend(sorted(base.rglob("*.py")))
    return files


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_no_legacy_settings_import_in_commands_and_usecases():
    pattern = re.compile(r"from\s+connector\.config\.config\s+import\s+.*\bSettings\b")
    violations: list[str] = []

    for path in _python_files("connector/delivery/commands", "connector/usecases"):
        text = _read(path)
        if pattern.search(text):
            violations.append(path.relative_to(ROOT).as_posix())

    assert violations == [], f"Legacy Settings import is forbidden in commands/usecases: {violations}"


def test_no_ctx_settings_or_obj_settings_usage_in_runtime_paths():
    violations: list[str] = []

    for path in _python_files("connector/delivery/commands", "connector/delivery/cli", "connector/usecases"):
        text = _read(path)
        if "ctx.settings" in text or 'obj["settings"]' in text or "obj['settings']" in text:
            violations.append(path.relative_to(ROOT).as_posix())

    assert violations == [], f"Legacy settings access is forbidden: {violations}"


def test_legacy_settings_api_not_used_in_connector_code():
    violations: list[str] = []
    patterns = (re.compile(r"\bloadSettings\b"), re.compile(r"\bfrom_legacy\b"))

    for path in _python_files("connector"):
        text = _read(path)
        if any(pattern.search(text) for pattern in patterns):
            violations.append(path.relative_to(ROOT).as_posix())

    assert violations == [], f"Legacy settings API is forbidden in connector code: {violations}"


def test_load_app_settings_used_only_in_composition_root_and_config_layer():
    allowed = {
        "connector/config/__init__.py",
        "connector/config/app_settings.py",
        "connector/config/loader.py",  # config-layer: documents what it replaces
        "connector/delivery/cli/app.py",
    }
    violations: list[str] = []
    pattern = re.compile(r"\bload_app_settings\b")

    for path in _python_files("connector"):
        rel = path.relative_to(ROOT).as_posix()
        if rel in allowed:
            continue
        text = _read(path)
        if pattern.search(text):
            violations.append(rel)

    assert violations == [], f"load_app_settings leakage outside composition root: {violations}"
