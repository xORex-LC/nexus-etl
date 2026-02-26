from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import os
import yaml


@dataclass(frozen=True)
class SettingsIssue:
    """
    Унифицированный payload ошибки/предупреждения конфигурации.
    """

    code: str
    field_path: str
    source: str
    raw_value: Any
    message: str
    hint: str


class SettingsLoadError(RuntimeError):
    """
    Базовая типизированная ошибка загрузки настроек.
    """

    def __init__(self, message: str, issues: list[SettingsIssue]) -> None:
        super().__init__(message)
        self.issues = issues


class SettingsSourceError(SettingsLoadError):
    """Ошибка чтения источника config/env/cli."""


def read_yaml_config(path: Path) -> dict:
    """
    Назначение:
        Читает YAML конфиг, возвращает словарь настроек.
    """
    if not path.exists():
        raise FileNotFoundError(f"Config file does not exist: {path}")
    if not path.is_file():
        raise IsADirectoryError(f"Config path is not a file: {path}")
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError("Top-level YAML structure must be a mapping/object")
    return data


def env_get(name: str) -> str | None:
    """
    Назначение:
        Получает переменную окружения и нормализует значение.
    """
    v = os.getenv(name)
    if v is None:
        return None
    vv = v.strip()
    if vv == "":
        return None
    return vv
