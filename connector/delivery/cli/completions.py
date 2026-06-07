"""CLI shell-completion callbacks — side-effect-free value-дополнители.

Модуль хранит `autocompletion`-коллбеки для Typer-опций. Дополнение команд,
подкоманд и флагов Typer выводит сам из дерева команд; здесь — только дополнение
ЗНАЧЕНИЙ «открытых» опций (датасет, путь, vault-mode), которые нельзя выразить
типом-enum.

Границы ответственности:
    - Дополнять значения опций из канонических источников (registry, fs-layout).
    - Делегировать файловое/каталожное дополнение встроенному Click.

Вне ответственности:
    - Определение enum-значений (их дополняет Typer из типа автоматически).
    - Любой runtime-bootstrap (DI, orchestrator, observability, vault, сеть).

Контракт коллбека (критично):
    Click вызывает коллбек в подпроцессе на КАЖДЫЙ TAB. Поэтому он обязан быть
    быстрым и БЕЗ сайд-эффектов: никакого DI-контейнера, orchestrator/observability,
    vault/SQLite-записи, HTTP. Только дешёвое чтение канонических источников; любая
    ошибка гасится в пустой список, чтобы tab-complete никогда не падал.
"""

from __future__ import annotations

import glob
import os

_VAULT_MODES = ("auto", "on", "off")
_PLAN_GLOBS = ("var/plans/*/*.json", "var/plans/*.json")


def complete_dataset(incomplete: str) -> list[str]:
    """Дополнить имя датасета из registry.yaml (без инстанцирования spec'ов).

    Импорт реестра отложен внутрь коллбека: модуль `completions` грузится при
    импорте CLI-дерева (для `autocompletion=`), а тянуть domain-граф ради этого
    на каждый TAB не нужно — он понадобится только при дополнении `--dataset`.
    """
    from connector.datasets.registry import list_dataset_names

    try:
        names = list_dataset_names()
    except Exception:
        return []
    return [name for name in names if name.startswith(incomplete)]


def complete_vault_mode(incomplete: str) -> list[str]:
    """Дополнить значение --vault-mode фиксированным набором auto|on|off."""
    return [mode for mode in _VAULT_MODES if mode.startswith(incomplete)]


def complete_path(incomplete: str) -> list[str]:
    """Дополнить путь к файлу/каталогу (glob по вводу пользователя).

    Typer-контракт `autocompletion` принимает только `list[str]` (не Click
    `CompletionItem`), поэтому файловое дополнение делаем явным glob'ом, а не
    shell-directive. Каталоги получают завершающий `/` для удобного спуска.
    """
    return _fs_matches(incomplete, dirs_only=False)


def complete_dir(incomplete: str) -> list[str]:
    """Дополнить путь к каталогу (glob, только директории)."""
    return _fs_matches(incomplete, dirs_only=True)


def complete_plan(incomplete: str) -> list[str]:
    """Дополнить путь к plan.json: подсказки из var/plans + общий файловый путь.

    Сперва предлагаются реально существующие планы из стандартной observability
    раскладки `var/plans/<component>/...`, затем — обычные файловые совпадения,
    чтобы пользователь мог указать план в любом месте. Лишнее Typer отфильтрует
    по `startswith(incomplete)`.
    """
    seen: set[str] = set()
    results: list[str] = []
    for pattern in _PLAN_GLOBS:
        for match in sorted(glob.glob(pattern)):
            if match not in seen:
                seen.add(match)
                results.append(match)
    for match in _fs_matches(incomplete, dirs_only=False):
        if match not in seen:
            seen.add(match)
            results.append(match)
    return results


def _fs_matches(incomplete: str, *, dirs_only: bool) -> list[str]:
    """Вернуть файловые/каталожные совпадения по `incomplete` (glob, cwd-relative)."""
    matches: list[str] = []
    for path in sorted(glob.glob(incomplete + "*")):
        is_dir = os.path.isdir(path)
        if dirs_only and not is_dir:
            continue
        matches.append(path + os.sep if is_dir else path)
    return matches


__all__ = [
    "complete_dataset",
    "complete_dir",
    "complete_path",
    "complete_plan",
    "complete_vault_mode",
]
