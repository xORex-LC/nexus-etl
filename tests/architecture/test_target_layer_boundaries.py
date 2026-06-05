"""
Архитектурные guard-тесты для границ target-слоя.

Зачем нужны эти тесты:
1. Команды delivery не должны импортировать низкоуровневые HTTP infra-модули.
2. Команды delivery не должны напрямую импортировать Ankey-специфичные классы/исключения.
3. Usecases/domain не должны зависеть от `connector.infra.target`.
4. Legacy-файлы target-cleanup не должны возвращаться в репозиторий.
"""

from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CONNECTOR_ROOT = REPO_ROOT / "connector"
COMMANDS_ROOT = REPO_ROOT / "connector" / "delivery" / "commands"
USECASES_ROOT = REPO_ROOT / "connector" / "usecases"
DOMAIN_ROOT = REPO_ROOT / "connector" / "domain"
CACHE_REFRESH_USECASE = (
    REPO_ROOT / "connector" / "usecases" / "cache_refresh_service.py"
)
TARGET_GATEWAY_CORE = (
    REPO_ROOT / "connector" / "infra" / "target" / "core" / "gateway.py"
)
TARGET_EXECUTION_PORT = (
    REPO_ROOT / "connector" / "domain" / "ports" / "target" / "execution.py"
)
TARGET_DRIVER_CONTRACT = REPO_ROOT / "connector" / "infra" / "target" / "driver.py"
TARGET_SAFE_LOGGING_ENGINE = (
    REPO_ROOT
    / "connector"
    / "infra"
    / "target"
    / "core"
    / "engines"
    / "safe_logging.py"
)
TARGET_FACTORY_CORE = (
    REPO_ROOT / "connector" / "infra" / "target" / "core" / "factory.py"
)

FORBIDDEN_ANKEY_NAMES = {
    "AnkeyApiClient",
    "ApiError",
    "AnkeyRequestExecutor",
    "AnkeyTargetPagedReader",
}
FORBIDDEN_BOOTSTRAP_BUILDERS = {
    "build_api_client",
    "build_api_executor",
    "build_api_reader",
}
LEGACY_TARGET_PATHS = (
    "connector/infra/target/legacy/__init__.py",
    "connector/infra/target/legacy/runtime.py",
    "connector/infra/target/legacy/ankey_paged_reader.py",
    "connector/infra/target/ankey_gateway.py",
    "connector/infra/target/providers/ankey/__init__.py",
    "connector/infra/target/providers/ankey/provider.py",
    "connector/infra/target/factory.py",
    "connector/infra/target/runtime.py",
    "connector/infra/target/gateway.py",
    "connector/infra/target/kernel.py",
    "connector/infra/target/models.py",
    "connector/infra/target/spec.py",
    "connector/infra/target/spec_ankey.py",
    "connector/infra/target/engines/__init__.py",
    "connector/infra/target/engines/retry_engine.py",
    "connector/infra/target/engines/error_normalizer.py",
    "connector/infra/target/engines/safe_logging.py",
    "connector/infra/target/core/contracts.py",
    "connector/datasets/employees/load/user_payload.py",
)
FORBIDDEN_RUNTIME_DEPENDENCIES = ("tenacity", "structlog", "pydantic_settings")
ALLOWED_TENACITY_IMPORT_PATHS = {
    "connector/infra/target/core/engines/retry_engine.py",
}
ALLOWED_STRUCTLOG_IMPORT_PATHS = {
    "connector/infra/target/core/engines/safe_logging.py",
    "connector/infra/logging/runtime.py",
    "connector/infra/dictionaries/telemetry.py",
    # structlog-forward-adoption: новые usecase-модули используют structlog (DEC-001)
    "connector/usecases/resolve_usecase.py",
    # vault-management: usecase/delivery/infra management modules log through structlog
    "connector/usecases/management/vault/maintenance.py",
    "connector/usecases/management/vault/usecase.py",
    "connector/delivery/commands/vault_management.py",
    "connector/infra/secrets/management/admin_password_gate.py",
}
FORBIDDEN_CORE_LITERALS = ("resourceexists", "health.check")
FORBIDDEN_TARGET_LEGACY_LITERALS = ("response_json", "body_snippet")


def _py_files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*.py") if p.is_file()]


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
    return imports


def _import_froms(path: Path) -> list[tuple[str, list[str]]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: list[tuple[str, list[str]]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names = [alias.name for alias in node.names]
            result.append((node.module or "", names))
    return result


def _rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def _violations(root: Path, forbidden_prefixes: tuple[str, ...]) -> list[str]:
    bad: list[str] = []
    for path in _py_files(root):
        rel = _rel(path)
        for module in _imports(path):
            if module.startswith(forbidden_prefixes):
                bad.append(f"{rel}: {module}")
    return bad


def test_delivery_commands_do_not_import_infra_http() -> None:
    violations = _violations(COMMANDS_ROOT, ("connector.infra.http",))
    assert violations == [], "Найдены запрещённые импорты:\n" + "\n".join(violations)


def test_delivery_commands_do_not_import_ankey_classes() -> None:
    violations: list[str] = []
    for path in _py_files(COMMANDS_ROOT):
        rel = _rel(path)
        for module, names in _import_froms(path):
            for name in names:
                if name in FORBIDDEN_ANKEY_NAMES:
                    violations.append(f"{rel}: from {module} import {name}")
    assert violations == [], "Найдены запрещённые импорты Ankey:\n" + "\n".join(
        violations
    )


def test_delivery_commands_do_not_use_legacy_bootstrap_builders() -> None:
    violations: list[str] = []
    for path in _py_files(COMMANDS_ROOT):
        rel = _rel(path)
        for module, names in _import_froms(path):
            if module != "connector.delivery.cli.bootstrap":
                continue
            for name in names:
                if name in FORBIDDEN_BOOTSTRAP_BUILDERS:
                    violations.append(f"{rel}: from {module} import {name}")
    assert violations == [], "Найдены запрещённые bootstrap-билдеры:\n" + "\n".join(
        violations
    )


def test_legacy_target_cleanup_files_are_removed() -> None:
    existing = [path for path in LEGACY_TARGET_PATHS if (REPO_ROOT / path).exists()]
    assert existing == [], "Legacy target-файлы должны быть удалены:\n" + "\n".join(
        existing
    )


def test_usecases_do_not_import_target_infra() -> None:
    violations = _violations(USECASES_ROOT, ("connector.infra.target",))
    assert violations == [], "Найдены запрещённые импорты:\n" + "\n".join(violations)


def test_domain_does_not_import_target_infra() -> None:
    violations = _violations(DOMAIN_ROOT, ("connector.infra.target",))
    assert violations == [], "Найдены запрещённые импорты:\n" + "\n".join(violations)


def test_cache_refresh_uses_operation_alias_instead_of_raw_target_path() -> None:
    tree = ast.parse(
        CACHE_REFRESH_USECASE.read_text(encoding="utf-8"),
        filename=str(CACHE_REFRESH_USECASE),
    )
    attrs = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert "list_path" not in attrs, (
        "cache refresh не должен зависеть от сырых target-путей"
    )
    assert "list_operation_alias" in attrs, (
        "cache refresh должен использовать operation alias из DSL-адаптера"
    )


def test_employees_spec_legacy_file_removed() -> None:
    legacy = REPO_ROOT / "connector" / "datasets" / "employees" / "spec.py"
    assert not legacy.exists(), (
        "employees/spec.py должен быть удалён — DEC-009 заменил его на YamlDatasetSpec"
    )


def test_domain_usecases_delivery_do_not_import_target_core_external_libs() -> None:
    violations: list[str] = []
    for root in (DOMAIN_ROOT, USECASES_ROOT, COMMANDS_ROOT):
        for path in _py_files(root):
            rel = _rel(path)
            # structlog-forward-adoption: usecases, перечисленные в ALLOWED_STRUCTLOG_IMPORT_PATHS,
            # разрешены к использованию structlog
            if rel in ALLOWED_STRUCTLOG_IMPORT_PATHS:
                continue
            for module in _imports(path):
                if module.startswith(FORBIDDEN_RUNTIME_DEPENDENCIES):
                    violations.append(f"{rel}: {module}")
    assert violations == [], (
        "Найдены запрещённые импорты runtime-зависимостей:\n" + "\n".join(violations)
    )


def test_tenacity_and_structlog_are_confined_to_target_engines() -> None:
    violations: list[str] = []
    for path in _py_files(CONNECTOR_ROOT):
        rel = _rel(path)
        modules = _imports(path)
        if any(module.startswith("tenacity") for module in modules):
            if rel not in ALLOWED_TENACITY_IMPORT_PATHS:
                violations.append(f"{rel}: импорт tenacity вне target engines")
        if any(module.startswith("structlog") for module in modules):
            if rel not in ALLOWED_STRUCTLOG_IMPORT_PATHS:
                violations.append(f"{rel}: импорт structlog вне target engines")
    assert violations == [], (
        "Нарушены границы зависимостей target runtime:\n" + "\n".join(violations)
    )


def test_target_gateway_core_has_no_provider_reason_or_hardcoded_health_alias() -> None:
    source = TARGET_GATEWAY_CORE.read_text(encoding="utf-8")
    violations = [literal for literal in FORBIDDEN_CORE_LITERALS if literal in source]
    assert violations == [], (
        "core gateway не должен содержать provider-специфичные literals "
        "или hardcoded health alias:\n" + "\n".join(violations)
    )


def test_target_neutral_contracts_do_not_reintroduce_legacy_literals() -> None:
    violations: list[str] = []
    files = (
        TARGET_EXECUTION_PORT,
        TARGET_DRIVER_CONTRACT,
        TARGET_GATEWAY_CORE,
        TARGET_SAFE_LOGGING_ENGINE,
    )
    for path in files:
        source = path.read_text(encoding="utf-8")
        for literal in FORBIDDEN_TARGET_LEGACY_LITERALS:
            if literal in source:
                violations.append(f"{_rel(path)}: {literal}")
    assert violations == [], (
        "В target neutral слоях не должны возвращаться legacy-поля:\n"
        + "\n".join(violations)
    )


def test_target_factory_core_does_not_import_concrete_provider() -> None:
    source = TARGET_FACTORY_CORE.read_text(encoding="utf-8")
    assert "providers.ankey_rest" not in source, (
        "core factory не должен импортировать конкретный провайдер напрямую"
    )
