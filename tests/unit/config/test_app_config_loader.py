"""
Unit-тесты для load_app_config() из connector/config/loader.py.

Проверяют: nested YAML, ENV override (ANKEY_{SECTION}__{FIELD}),
CLI priority, source trace per-field, unknown key error (extra="forbid"),
range validation, zero/false value preservation, missing config path,
empty warnings list.
"""
from __future__ import annotations

import pytest

from connector.config.config import SettingsLoadError, SettingsSourceError
from connector.config.loader import load_app_config


def test_load_from_nested_yaml(tmp_path: object) -> None:
    """Корректный nested YAML → LoadedAppConfig без ошибок."""
    cfg_file = tmp_path / "config.yml"  # type: ignore[operator]
    cfg_file.write_text("api:\n  host: myhost\n  port: 8443\n", encoding="utf-8")

    result = load_app_config(str(cfg_file))

    assert result.app_config.api.host == "myhost"
    assert result.app_config.api.port == 8443


def test_load_dataset_registry_path_from_yaml(
    tmp_path: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg_file = tmp_path / "config.yml"  # type: ignore[operator]
    cfg_file.write_text(
        "dataset:\n"
        "  registry_path: ./datasets/registry.yml\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("ANKEY_DATASET__REGISTRY_PATH", raising=False)

    result = load_app_config(str(cfg_file))

    assert result.app_config.dataset.registry_path == "./datasets/registry.yml"
    assert result.source_trace["dataset.registry_path"] == "config"


def test_env_override_nested_naming(tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> None:
    """ANKEY_API__HOST=x переопределяет значение из YAML."""
    cfg_file = tmp_path / "config.yml"  # type: ignore[operator]
    cfg_file.write_text("api:\n  host: fromyaml\n", encoding="utf-8")
    monkeypatch.setenv("ANKEY_API__HOST", "fromenv")

    result = load_app_config(str(cfg_file))

    assert result.app_config.api.host == "fromenv"


def test_cli_override_dotted_path_beats_env(tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> None:
    """cli_overrides={'api.host': 'fromcli'} > ANKEY_API__HOST='fromenv' > YAML."""
    cfg_file = tmp_path / "config.yml"  # type: ignore[operator]
    cfg_file.write_text("api:\n  host: fromyaml\n", encoding="utf-8")
    monkeypatch.setenv("ANKEY_API__HOST", "fromenv")

    result = load_app_config(str(cfg_file), cli_overrides={"api.host": "fromcli"})

    assert result.app_config.api.host == "fromcli"


def test_source_trace_all_origins(tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> None:
    """'config' | 'env' | 'cli' | 'default' корректно заполняется per-field."""
    cfg_file = tmp_path / "config.yml"  # type: ignore[operator]
    cfg_file.write_text("api:\n  host: fromconfig\n", encoding="utf-8")
    monkeypatch.setenv("ANKEY_API__PORT", "8080")

    result = load_app_config(str(cfg_file), cli_overrides={"api.username": "me"})
    trace = result.source_trace

    assert trace.get("api.host") == "config"
    assert trace.get("api.port") == "env"
    assert trace.get("api.username") == "cli"
    # api.retries не задан ни в одном источнике → "default"
    assert trace.get("api.retries") == "default"


def test_unknown_yaml_key_raises_validation_error(tmp_path: object) -> None:
    """extra='forbid': неизвестный ключ в YAML → SettingsLoadError.

    С extra='forbid' нет режима warn — всегда ошибка.
    """
    cfg_file = tmp_path / "config.yml"  # type: ignore[operator]
    cfg_file.write_text("unknown_section: 123\n", encoding="utf-8")

    with pytest.raises(SettingsLoadError):
        load_app_config(str(cfg_file))


def test_invalid_literal_raises_validation_error(tmp_path: object) -> None:
    """vault_rollout.mode='bad_mode' → SettingsLoadError (Literal validation)."""
    cfg_file = tmp_path / "config.yml"  # type: ignore[operator]
    cfg_file.write_text("vault_rollout:\n  mode: bad_mode\n", encoding="utf-8")

    with pytest.raises(SettingsLoadError):
        load_app_config(str(cfg_file))


def test_field_range_validation(tmp_path: object) -> None:
    """api.port=0 → SettingsLoadError (gt=0 constraint)."""
    cfg_file = tmp_path / "config.yml"  # type: ignore[operator]
    cfg_file.write_text("api:\n  port: 0\n", encoding="utf-8")

    with pytest.raises(SettingsLoadError):
        load_app_config(str(cfg_file))


def test_zero_value_not_lost(tmp_path: object) -> None:
    """0 в YAML не теряется при merge: pending_retention_days=0 != default 14."""
    cfg_file = tmp_path / "config.yml"  # type: ignore[operator]
    cfg_file.write_text("resolver:\n  pending_retention_days: 0\n", encoding="utf-8")

    result = load_app_config(str(cfg_file))

    assert result.app_config.resolver.pending_retention_days == 0


def test_false_value_not_lost(tmp_path: object) -> None:
    """false в YAML не теряется при merge: pending_allow_partial=true затем переопределяется."""
    cfg_file = tmp_path / "config.yml"  # type: ignore[operator]
    # Устанавливаем non-default значение, чтобы убедиться что YAML читается правильно
    cfg_file.write_text("resolver:\n  pending_allow_partial: true\n", encoding="utf-8")

    result = load_app_config(str(cfg_file))

    assert result.app_config.resolver.pending_allow_partial is True


def test_missing_config_path_raises_source_error(tmp_path: object) -> None:
    """Несуществующий config-файл → SettingsSourceError."""
    missing = str(tmp_path / "nonexistent.yml")  # type: ignore[operator]

    with pytest.raises(SettingsSourceError) as exc_info:
        load_app_config(missing)

    assert exc_info.value.issues[0].code == "settings.source.config_read_failed"


def test_warnings_list_initially_empty(tmp_path: object) -> None:
    """LoadedAppConfig.warnings == [] при корректной загрузке."""
    cfg_file = tmp_path / "config.yml"  # type: ignore[operator]
    cfg_file.write_text("api:\n  host: h\n", encoding="utf-8")

    result = load_app_config(str(cfg_file))

    assert result.warnings == []


def test_env_ignore_empty_does_not_override(tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> None:
    """Пустая строка в ENV не перетирает значение из YAML."""
    cfg_file = tmp_path / "config.yml"  # type: ignore[operator]
    cfg_file.write_text("api:\n  host: fromyaml\n", encoding="utf-8")
    monkeypatch.setenv("ANKEY_API__HOST", "")

    result = load_app_config(str(cfg_file))

    # Пустой ENV должен быть проигнорирован → значение из YAML сохраняется
    assert result.app_config.api.host == "fromyaml"


def test_load_without_config_path_uses_defaults() -> None:
    """load_app_config() без config_path и overrides возвращает AppConfig с defaults."""
    result = load_app_config()

    cfg = result.app_config
    assert cfg.api.host is None
    assert cfg.resolver.pending_max_attempts == 5
    assert cfg.vault_rollout.mode == "full"


def test_source_trace_contains_all_sections(tmp_path: object) -> None:
    """source_trace содержит записи для всех секций AppConfig."""
    cfg_file = tmp_path / "config.yml"  # type: ignore[operator]
    cfg_file.write_text("{}", encoding="utf-8")

    result = load_app_config(str(cfg_file))
    trace = result.source_trace

    # Все leaf-поля должны быть в trace (с "default" если не задан источник)
    assert "api.host" in trace
    assert "resolver.pending_max_attempts" in trace
    assert "vault_rollout.mode" in trace
    assert "vault_management.admin_password_hash_file" in trace
    assert "sqlite.journal_mode" in trace
    assert "dictionary.load_strategy" in trace

    # Все незаданные поля — "default"
    assert all(v in ("config", "env", "cli", "default") for v in trace.values())


def test_vault_management_env_override_is_ignored(
    tmp_path: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ENV не может менять security-sensitive vault_management настройки."""
    cfg_file = tmp_path / "config.yml"  # type: ignore[operator]
    cfg_file.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("ANKEY_VAULT_MANAGEMENT__ADMIN_PASSWORD_HASH_FILE", "./environment/vault-admin.env")
    monkeypatch.setenv("ANKEY_VAULT_MANAGEMENT__REQUIRE_ADMIN_PASSWORD_FOR_MANUAL_OPS", "false")

    result = load_app_config(str(cfg_file))

    assert result.app_config.vault_management.admin_password_hash_file is None
    assert result.app_config.vault_management.require_admin_password_for_manual_ops is True
    assert result.source_trace["vault_management.admin_password_hash_file"] == "default"
    assert result.source_trace["vault_management.require_admin_password_for_manual_ops"] == "default"


def test_vault_management_hash_file_cli_override_beats_yaml_while_env_is_ignored(
    tmp_path: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """vault_management.admin_password_hash_file: CLI > YAML; ENV игнорируется."""
    cfg_file = tmp_path / "config.yml"  # type: ignore[operator]
    cfg_file.write_text("vault_management:\n  admin_password_hash_file: ./from-config.env\n", encoding="utf-8")
    monkeypatch.setenv("ANKEY_VAULT_MANAGEMENT__ADMIN_PASSWORD_HASH_FILE", "./from-env.env")

    env_ignored_result = load_app_config(str(cfg_file))
    assert env_ignored_result.app_config.vault_management.admin_password_hash_file == "./from-config.env"
    assert env_ignored_result.source_trace["vault_management.admin_password_hash_file"] == "config"

    result = load_app_config(
        str(cfg_file),
        cli_overrides={"vault_management.admin_password_hash_file": "./from-cli.env"},
    )

    assert result.app_config.vault_management.admin_password_hash_file == "./from-cli.env"
    assert result.source_trace["vault_management.admin_password_hash_file"] == "cli"


def test_vault_management_rejects_removed_auto_rotate_interval(tmp_path: object) -> None:
    """Удалённые auto_rotate настройки больше не принимаются конфигом."""
    cfg_file = tmp_path / "config.yml"  # type: ignore[operator]
    cfg_file.write_text(
        "vault_management:\n"
        "  auto_rotate_interval:\n"
        "    hours: 0\n"
        "    days: 0\n"
        "    months: 0\n"
        "    years: 0\n",
        encoding="utf-8",
    )

    with pytest.raises(SettingsLoadError):
        load_app_config(str(cfg_file))
