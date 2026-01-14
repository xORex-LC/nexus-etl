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

        log_level: str
            Уровень логирования.
        log_json: bool
            Логировать в JSON формате.
        report_format: str
            Формат отчётов.
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

    log_level: str = "INFO"
    log_json: bool = False
    report_format: str = "json"

    # API/cache refresh tuning (Stage 5)
    page_size: int = 200
    max_pages: int = 1000
    timeout_seconds: float = 20.0
    retries: int = 3
    retry_backoff_seconds: float = 0.5
    include_deleted_users: bool = False
    report_items_limit: int = 200
    report_items_success: bool = False
    on_missing_org: str = "error"

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

def parseFloat(value: str | None) -> float | None:
    """
    Назначение:
        Преобразует строку в float, если значение задано.
    """
    if value is None:
        return None
    return float(value)

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

def parseIntAny(value: int | str | None) -> int | None:
    """
    Назначение:
        Нормализует целочисленное значение (int/str/None) в int|None.

    Входные данные:
        value: int | str | None

    Выходные данные:
        int | None
    """
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value.strip())
    raise ValueError(f"Invalid int value type: {type(value)}")


def parseBoolAny(value: bool | str | None) -> bool | None:
    """
    Назначение:
        Нормализует булевое значение (bool/str/None) в bool|None.

    Входные данные:
        value: bool | str | None

    Выходные данные:
        bool | None
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return parseBool(value.strip())
    raise ValueError(f"Invalid bool value type: {type(value)}")


def parseFloatAny(value: float | str | None) -> float | None:
    """
    Назначение:
        Нормализует значение (float/str/None) в float|None.
    """
    if value is None:
        return None
    if isinstance(value, (float, int)):
        return float(value)
    if isinstance(value, str):
        return float(value.strip())
    raise ValueError(f"Invalid float value type: {type(value)}")


def parseOnMissingOrg(value: str | None) -> str | None:
    """
    Назначение:
        Валидирует значение политики отсутствующей организации.
    """
    if value is None:
        return None
    v = value.strip().lower()
    if v in ("error", "warn-and-skip"):
        return v
    raise ValueError(f"Invalid on_missing_org value: {value}")

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
        "log_level": envGet("ANKEY_LOG_LEVEL"),
        "log_json": envGet("ANKEY_LOG_JSON"),
        "report_format": envGet("ANKEY_REPORT_FORMAT"),
        "page_size": envGet("ANKEY_PAGE_SIZE"),
        "max_pages": envGet("ANKEY_MAX_PAGES"),
        "timeout_seconds": envGet("ANKEY_TIMEOUT_SECONDS"),
        "retries": envGet("ANKEY_RETRIES"),
        "retry_backoff_seconds": envGet("ANKEY_RETRY_BACKOFF_SECONDS"),
        "include_deleted_users": envGet("ANKEY_INCLUDE_DELETED_USERS"),
        "report_items_limit": envGet("ANKEY_REPORT_ITEMS_LIMIT"),
        "report_items_success": envGet("ANKEY_REPORT_ITEMS_SUCCESS"),
        "on_missing_org": envGet("ANKEY_ON_MISSING_ORG"),
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

        "log_level": cfg.get("log_level", defaults.log_level),
        "log_json": cfg.get("log_json", defaults.log_json),
        "report_format": cfg.get("report_format", defaults.report_format),
        "page_size": cfg.get("page_size", defaults.page_size),
        "max_pages": cfg.get("max_pages", defaults.max_pages),
        "timeout_seconds": cfg.get("timeout_seconds", defaults.timeout_seconds),
        "retries": cfg.get("retries", defaults.retries),
        "retry_backoff_seconds": cfg.get("retry_backoff_seconds", defaults.retry_backoff_seconds),
        "include_deleted_users": cfg.get("include_deleted_users", defaults.include_deleted_users),
        "report_items_limit": cfg.get("report_items_limit", defaults.report_items_limit),
        "report_items_success": cfg.get("report_items_success", defaults.report_items_success),
        "on_missing_org": cfg.get("on_missing_org", defaults.on_missing_org),
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

    if env["log_level"] is not None:
        merged["log_level"] = env["log_level"]
    if env["log_json"] is not None:
        merged["log_json"] = parseBool(env["log_json"])
    if env["report_format"] is not None:
        merged["report_format"] = env["report_format"]
    if env["page_size"] is not None:
        merged["page_size"] = parseInt(env["page_size"])
    if env["max_pages"] is not None:
        merged["max_pages"] = parseInt(env["max_pages"])
    if env["timeout_seconds"] is not None:
        merged["timeout_seconds"] = parseFloat(env["timeout_seconds"])
    if env["retries"] is not None:
        merged["retries"] = parseInt(env["retries"])
    if env["retry_backoff_seconds"] is not None:
        merged["retry_backoff_seconds"] = parseFloat(env["retry_backoff_seconds"])
    if env["include_deleted_users"] is not None:
        merged["include_deleted_users"] = parseBool(env["include_deleted_users"])
    if env["report_items_limit"] is not None:
        merged["report_items_limit"] = parseInt(env["report_items_limit"])
    if env["report_items_success"] is not None:
        merged["report_items_success"] = parseBool(env["report_items_success"])
    if env["on_missing_org"] is not None:
        merged["on_missing_org"] = parseOnMissingOrg(env["on_missing_org"])

    if any(v is not None for v in cli_overrides.values()):
        sources.append("cli")
    for k, v in cli_overrides.items():
        if v is None:
            continue
        merged[k] = v

    settings = Settings(
        host=merged["host"],
        port=parseIntAny(merged["port"]),
        api_username=merged["api_username"],
        api_password=merged["api_password"],
        cache_dir=merged["cache_dir"],
        log_dir=merged["log_dir"],
        report_dir=merged["report_dir"],
        tls_skip_verify=parseBoolAny(merged["tls_skip_verify"]) or False,
        ca_file=merged["ca_file"],
        log_level=merged["log_level"],
        log_json=parseBoolAny(merged["log_json"]) or False,
        report_format=merged["report_format"],
        page_size=parseIntAny(merged["page_size"]) or defaults.page_size,
        max_pages=parseIntAny(merged["max_pages"]) or defaults.max_pages,
        timeout_seconds=parseFloatAny(merged["timeout_seconds"]) or defaults.timeout_seconds,
        retries=parseIntAny(merged["retries"]) or defaults.retries,
        retry_backoff_seconds=parseFloatAny(merged["retry_backoff_seconds"]) or defaults.retry_backoff_seconds,
        include_deleted_users=parseBoolAny(merged["include_deleted_users"]) or False,
        report_items_limit=parseIntAny(merged["report_items_limit"]) or defaults.report_items_limit,
        report_items_success=parseBoolAny(merged["report_items_success"]) or False,
        on_missing_org=parseOnMissingOrg(merged["on_missing_org"]) or defaults.on_missing_org,
    )

    return LoadedSettings(settings=settings, sources_used=sources)
