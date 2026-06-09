"""Unit-тесты CLI shell-completion: value-дополнители и включённость completion.

Проверяем, что коллбеки дополняют значения из канонических источников,
side-effect-free (ошибка источника → пустой список, без падения), и что
Typer-приложение действительно отдаёт completion команд/подкоманд.
"""

from __future__ import annotations

import os

import pytest
from click.shell_completion import ShellComplete
from typer.main import get_command

from connector.datasets import registry as registry_module
from connector.delivery.cli import completions
from connector.delivery.cli.app import app


@pytest.mark.unit
def test_complete_dataset_filters_by_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    # `complete_dataset` импортирует registry лениво (import-budget), поэтому
    # патчим источник, а не атрибут модуля completions.
    monkeypatch.setattr(
        registry_module, "list_dataset_names", lambda: ["employees", "organizations"]
    )
    assert completions.complete_dataset("emp") == ["employees"]
    assert completions.complete_dataset("") == ["employees", "organizations"]
    assert completions.complete_dataset("zzz") == []


@pytest.mark.unit
def test_complete_dataset_swallows_source_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom() -> list[str]:
        raise RuntimeError("registry unavailable")

    monkeypatch.setattr(registry_module, "list_dataset_names", _boom)
    assert completions.complete_dataset("emp") == []


@pytest.mark.unit
def test_complete_dataset_reads_real_registry() -> None:
    # Дешёвый side-effect-free аксессор должен видеть штатные датасеты.
    names = completions.complete_dataset("")
    assert "employees" in names


@pytest.mark.unit
def test_complete_vault_mode() -> None:
    assert completions.complete_vault_mode("o") == ["on", "off"]
    assert completions.complete_vault_mode("auto") == ["auto"]
    assert completions.complete_vault_mode("x") == []


@pytest.mark.unit
def test_complete_path_and_dir_return_str_matches(tmp_path, monkeypatch) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / "file.txt").write_text("x", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    # Typer's autocompletion contract accepts only list[str] (not CompletionItem).
    assert all(isinstance(v, str) for v in completions.complete_path(""))
    assert "file.txt" in completions.complete_path("")
    dirs = completions.complete_dir("")
    assert all(isinstance(v, str) for v in dirs)
    assert "sub" + os.sep in dirs
    assert "file.txt" not in dirs


@pytest.mark.unit
def test_complete_plan_includes_layout_and_fs(tmp_path, monkeypatch) -> None:
    plan = tmp_path / "var" / "plans" / "planner" / "2026-06-05T02-29-27_planner.json"
    plan.parent.mkdir(parents=True)
    plan.write_text("{}", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    results = completions.complete_plan("")
    assert all(isinstance(v, str) for v in results)
    assert "var/plans/planner/2026-06-05T02-29-27_planner.json" in results


@pytest.mark.unit
def test_app_has_completion_enabled() -> None:
    command = get_command(app)
    param_names = {param.name for param in command.params}
    assert "install_completion" in param_names
    assert "show_completion" in param_names


@pytest.mark.unit
def test_shell_completion_lists_top_level_commands() -> None:
    command = get_command(app)
    shell = ShellComplete(command, {}, "nexus", "_NEXUS_COMPLETE")
    names = {item.value for item in shell.get_completions([], "")}
    assert {"import", "cache", "obs", "vault-management"} <= names


@pytest.mark.unit
def test_import_group_contains_plan_and_apply_subcommands() -> None:
    command = get_command(app)
    import_command = command.commands["import"]
    assert {"plan", "apply"} <= set(import_command.commands)


@pytest.mark.unit
def test_mapping_dataset_option_is_wired_to_dataset_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        registry_module, "list_dataset_names", lambda: ["employees", "organizations"]
    )
    command = get_command(app)
    mapping_command = command.commands["mapping"]
    dataset_option = next(
        param for param in mapping_command.params if param.name == "dataset"
    )
    with mapping_command.make_context("mapping", [], resilient_parsing=True) as ctx:
        names = {item.value for item in dataset_option.shell_complete(ctx, "")}
    assert {"employees", "organizations"} <= names


@pytest.mark.unit
@pytest.mark.parametrize(
    "args",
    [
        ["--config"],
        ["--log-dir"],
        ["--report-dir"],
        ["--cache-dir"],
        ["--ca-file"],
        ["--api-password-file"],
        ["import", "apply", "--plan"],
        ["import", "plan", "--vault-mode"],
    ],
)
def test_shell_completion_value_callbacks_do_not_raise(args: list[str]) -> None:
    """Прогон value-коллбеков через настоящий Typer/Click shim.

    Регрессия: Typer `autocompletion` принимает только `list[str]`/`list[tuple]`;
    возврат Click `CompletionItem` падает с AssertionError на двойной TAB. Этот
    тест ловит такой класс ошибок именно на уровне shim, а не прямого вызова.
    """
    command = get_command(app)
    shell = ShellComplete(command, {}, "nexus", "_NEXUS_COMPLETE")
    # Не должно бросать; значения — строки.
    items = shell.get_completions(args, "")
    assert all(isinstance(item.value, str) for item in items)
