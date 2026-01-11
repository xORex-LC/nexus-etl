from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import yaml


@dataclass(frozen=True)
class Settings:
    """
    Назначение:
        Консолидированные настройки приложения после мерджа:
        CLI > ENV > config > defaults.

    Поля:
        host: str | None
            IP/hostname API.
        port: int | None
            Порт API.
        api_username: str | None
            Пользователь API.
        api_password: str | None
            Пароль пользователя API.

        cache_dir: str
            Каталог кэша.
        log_dir: str
            Каталог логов.
        report_dir: str
            Каталог отчётов.

        tls_skip_verify: bool
            Отключить проверку TLS сертификата.
        ca_file: str | None
            Путь к CA-файлу (если используется проверка TLS через CA).
    """
    host: str | None = None
    port: int | None = None
    api_username: str | None = None
    api_password: str | None = None

    cache_dir: str = "./cache"
    log_dir: str = "./logs"
    report_dir: str = "./reports"

    tls_skip_verify: bool = False
    ca_file: str | None = None


@dataclass(frozen=True)
class LoadedSettings:
    """
    Назначение:
        Результат загрузки настроек с информацией об источниках.

    Поля:
        settings: Settings
            Итоговые настройки.
        sources_used: list[str]
            Список источников, которые реально участвовали в формировании
            настроек (например: ["config", "env", "cli"]).
    """
    settings: Settings
    sources_used: list[str]


def readYamlConfig(path: Path) -> dict:
    """
    Назначение:
        Читает YAML конфиг, возвращает словарь настроек.

    Входные данные:
        path: Path
            Путь к YAML файлу конфигурации.

    Выходные данные:
        dict
            Словарь с настройками из YAML или пустой dict, если файл
            отсутствует/некорректен.

    Алгоритм:
        - Проверить существование и тип файла.
        - Прочитать YAML и убедиться, что верхний уровень — dict.
    """
    if not path.exists():
        return {}
    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            return {}
        return data


def envGet(name: str) -> str | None:
    """
    Назначение:
        Получает переменную окружения и нормализует значение.

    Входные данные:
        name: str
            Имя переменной окружения.

    Выходные данные:
        str | None
            Строка без пробелов по краям или None, если пусто/не задано.
    """
    v = os.getenv(name)
    if v is None or v.strip() == "":
        return None
    return v.strip()


def parseInt(value: str | None) -> int | None:
    """
    Назначение:
        Преобразует строку в int, если значение задано.

    Входные данные:
        value: str | None

    Выходные данные:
        int | None

    Исключения:
        ValueError — если строка не является целым числом.
    """
    if value is None:
        return None
    return int(value)


def parseBool(value: str | None) -> bool | None:
    """
    Назначение:
        Преобразует строковое значение в bool по набору допустимых вариантов.

    Входные данные:
        value: str | None

    Выходные данные:
        bool | None

    Допустимые значения (case-insensitive):
        true/1/yes/y  -> True
        false/0/no/n  -> False

    Исключения:
        ValueError — если значение не распознано как bool.
    """
    if value is None:
        return None
    vv = value.lower()
    if vv in ("1", "true", "yes", "y"):
        return True
    if vv in ("0", "false", "no", "n"):
        return False
    raise ValueError(f"Invalid boolean env value: {value}")


def loadSettings(config_path: str | None, cli_overrides: dict) -> LoadedSettings:
    """
    Назначение:
        Загружает настройки приложения, применяя приоритет:
        CLI > ENV > config > defaults.

    Входные данные:
        config_path: str | None
            Путь к YAML конфигу. Если None — конфиг не читается.
        cli_overrides: dict
            Словарь значений из CLI. Значения None считаются "не задано".

    Выходные данные:
        LoadedSettings
            Итоговые настройки и список использованных источников.

    Алгоритм:
        1) Сформировать defaults.
        2) Прочитать config (если задан).
        3) Прочитать ENV (если задано хоть что-то).
        4) Наложить CLI overrides (только не-None).
    """
    sources: list[str] = []
    defaults = Settings()

    cfg: dict = {}
    if config_path:
        cfg = readYamlConfig(Path(config_path))
        if cfg:
            sources.append("config")

    env = {
        "host": envGet("ANKEY_API_HOST"),
        "port": envGet("ANKEY_API_PORT"),
        "api_username": envGet("ANKEY_API_USERNAME"),
        "api_password": envGet("ANKEY_API_PASSWORD"),
        "cache_dir": envGet("ANKEY_CACHE_DIR"),
        "log_dir": envGet("ANKEY_LOG_DIR"),
        "report_dir": envGet("ANKEY_REPORT_DIR"),
        "tls_skip_verify": envGet("ANKEY_TLS_SKIP_VERIFY"),
        "ca_file": envGet("ANKEY_CA_FILE"),
    }
    if any(v is not None for v in env.values()):
        sources.append("env")

    merged = {
        "host": cfg.get("host", defaults.host),
        "port": cfg.get("port", defaults.port),
        "api_username": cfg.get("api_username", defaults.api_username),
        "api_password": cfg.get("api_password", defaults.api_password),

        "cache_dir": cfg.get("cache_dir", defaults.cache_dir),
        "log_dir": cfg.get("log_dir", defaults.log_dir),
        "report_dir": cfg.get("report_dir", defaults.report_dir),

        "tls_skip_verify": cfg.get("tls_skip_verify", defaults.tls_skip_verify),
        "ca_file": cfg.get("ca_file", defaults.ca_file),
    }

    if env["host"] is not None:
        merged["host"] = env["host"]
    if env["port"] is not None:
        merged["port"] = parseInt(env["port"])
    if env["api_username"] is not None:
        merged["api_username"] = env["api_username"]
    if env["api_password"] is not None:
        merged["api_password"] = env["api_password"]

    if env["cache_dir"] is not None:
        merged["cache_dir"] = env["cache_dir"]
    if env["log_dir"] is not None:
        merged["log_dir"] = env["log_dir"]
    if env["report_dir"] is not None:
        merged["report_dir"] = env["report_dir"]

    if env["tls_skip_verify"] is not None:
        merged["tls_skip_verify"] = parseBool(env["tls_skip_verify"])
    if env["ca_file"] is not None:
        merged["ca_file"] = env["ca_file"]

    if any(v is not None for v in cli_overrides.values()):
        sources.append("cli")
    for k, v in cli_overrides.items():
        if v is None:
            continue
        merged[k] = v

    settings = Settings(
        host=merged["host"],
        port=merged["port"],
        api_username=merged["api_username"],
        api_password=merged["api_password"],
        cache_dir=merged["cache_dir"],
        log_dir=merged["log_dir"],
        report_dir=merged["report_dir"],
        tls_skip_verify=bool(merged["tls_skip_verify"]),
        ca_file=merged["ca_file"],
    )

    return LoadedSettings(settings=settings, sources_used=sources)