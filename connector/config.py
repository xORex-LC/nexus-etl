from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import yaml


@dataclass(frozen=True)
class Settings:
    # API
    host: str | None = None
    port: int | None = None
    api_username: str | None = None
    api_password: str | None = None

    # Paths
    cache_dir: str = "./cache"
    log_dir: str = "./logs"
    report_dir: str = "./reports"

    # Misc
    tls_skip_verify: bool = False
    ca_file: str | None = None


@dataclass(frozen=True)
class LoadedSettings:
    settings: Settings
    sources_used: list[str]


def _read_yaml_config(path: Path) -> dict:
    if not path.exists():
        return {}
    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            return {}
        return data


def _env_get(name: str) -> str | None:
    v = os.getenv(name)
    if v is None or v.strip() == "":
        return None
    return v.strip()


def load_settings(
    config_path: str | None,
    cli_overrides: dict,
) -> LoadedSettings:
    """
    Priority: CLI > ENV > config > defaults
    """
    sources: list[str] = []
    defaults = Settings()

    # 1) config file
    cfg: dict = {}
    if config_path:
        cfg = _read_yaml_config(Path(config_path))
        if cfg:
            sources.append("config")

    # 2) env
    env = {
        "host": _env_get("ANKEY_API_HOST"),
        "port": _env_get("ANKEY_API_PORT"),
        "api_username": _env_get("ANKEY_API_USERNAME"),
        "api_password": _env_get("ANKEY_API_PASSWORD"),
        "cache_dir": _env_get("ANKEY_CACHE_DIR"),
        "log_dir": _env_get("ANKEY_LOG_DIR"),
        "report_dir": _env_get("ANKEY_REPORT_DIR"),
        "tls_skip_verify": _env_get("ANKEY_TLS_SKIP_VERIFY"),
        "ca_file": _env_get("ANKEY_CA_FILE"),
    }
    if any(v is not None for v in env.values()):
        sources.append("env")

    def parse_int(v: str | None) -> int | None:
        if v is None:
            return None
        return int(v)

    def parse_bool(v: str | None) -> bool | None:
        if v is None:
            return None
        vv = v.lower()
        if vv in ("1", "true", "yes", "y"):
            return True
        if vv in ("0", "false", "no", "n"):
            return False
        raise ValueError(f"Invalid boolean env value: {v}")

    # merge config -> env -> cli
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

    # apply env
    if env["host"] is not None:
        merged["host"] = env["host"]
    if env["port"] is not None:
        merged["port"] = parse_int(env["port"])
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
        merged["tls_skip_verify"] = parse_bool(env["tls_skip_verify"])
    if env["ca_file"] is not None:
        merged["ca_file"] = env["ca_file"]

    # 3) apply CLI overrides (only those explicitly passed)
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
