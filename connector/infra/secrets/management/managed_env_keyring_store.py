"""Назначение:
    Файловый store для managed keyring переменной `ANKEY_VAULT_MASTER_KEYS`.

Граница ответственности:
    - Отвечает только за filesystem-аспекты: парсинг/запись env-файла,
      atomic replace, контроль прав и межпроцессный lock.
    - Не реализует lifecycle orchestration (rotate/rewrap/delete),
      password-gate и планирование операций.
"""

from __future__ import annotations

import fcntl
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from connector.domain.ports.secrets.key_provider import VaultMasterKey
from connector.domain.secrets.errors import SecretKeyConfigError, SecretStoreError
from connector.infra.secrets.env_key_provider import DEFAULT_MASTER_KEYS_ENV, parse_master_keyring


class VaultManagedEnvKeyringStore:
    """
    Назначение:
        Filesystem-адаптер persisted keyring для vault-management.

    Инварианты:
        - запись файла атомарна (`tmp -> fsync(file) -> rename -> fsync(dir)`),
          поэтому читатели не увидят частично записанное содержимое;
        - права целевого файла принудительно выставляются в `0600`;
        - lifecycle-операции сериализуются через `flock` на отдельном lock-файле.
    """

    def __init__(self, managed_env_file: str, *, env_var: str = DEFAULT_MASTER_KEYS_ENV) -> None:
        self._path = Path(managed_env_file)
        self._lock_path = self._path.with_suffix(self._path.suffix + ".lock")
        self._env_var = env_var

    @property
    def lock_path(self) -> Path:
        """Путь к sidecar lock-файлу для сериализации lifecycle-операций."""
        return self._lock_path

    @contextmanager
    def lifecycle_lock(self) -> Iterator[None]:
        """Взять межпроцессный exclusive-lock для lifecycle-операций keyring."""
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = -1
        try:
            fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o600)
            os.fchmod(fd, 0o600)
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        except OSError as exc:
            raise SecretStoreError(
                "Failed to acquire managed keyring file lock",
                details={
                    "reason": "managed_env_lock_failed",
                    "path": str(self._lock_path),
                    "errno": getattr(exc, "errno", None),
                    "env_var": self._env_var,
                },
            ) from exc
        finally:
            if fd >= 0:
                try:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                finally:
                    os.close(fd)

    def load_keyring(self) -> tuple[VaultMasterKey, ...]:
        """Загрузить и распарсить keyring из managed env-файла под lifecycle-lock."""
        with self.lifecycle_lock():
            raw_value = self._read_env_var_value()
        return parse_master_keyring(raw_value, env_var=self._env_var)

    def save_keyring(self, keys: tuple[VaultMasterKey, ...]) -> None:
        """Атомарно сохранить keyring в managed env-файл под lifecycle-lock."""
        serialized = self._serialize_keyring(keys)
        with self.lifecycle_lock():
            self._atomic_write_env_value(serialized)

    def _read_env_var_value(self) -> str:
        if not self._path.exists():
            raise SecretKeyConfigError(
                "Managed vault env file does not exist",
                details={
                    "env_var": self._env_var,
                    "reason": "managed_env_file_missing",
                    "path": str(self._path),
                },
            )
        try:
            content = self._path.read_text(encoding="utf-8")
        except OSError as exc:
            raise SecretStoreError(
                "Failed to read managed vault env file",
                details={
                    "reason": "managed_env_read_failed",
                    "path": str(self._path),
                    "errno": getattr(exc, "errno", None),
                    "env_var": self._env_var,
                },
            ) from exc

        for raw_line in content.splitlines():
            value = _extract_env_value(raw_line, env_var=self._env_var)
            if value is not None:
                return value

        raise SecretKeyConfigError(
            "Managed vault env file does not contain keyring variable",
            details={
                "env_var": self._env_var,
                "reason": "managed_env_var_missing",
                "path": str(self._path),
            },
        )

    def _serialize_keyring(self, keys: tuple[VaultMasterKey, ...]) -> str:
        if not keys:
            raise SecretKeyConfigError(
                "Managed vault keyring cannot be empty",
                details={"env_var": self._env_var, "reason": "empty_keyring"},
            )
        raw = ",".join(f"{item.key_version}:{item.key_material}" for item in keys)
        # Переиспользуем канонический parser для строгой валидации
        # (уникальность версий + валидность формата Fernet).
        parse_master_keyring(raw, env_var=self._env_var)
        return raw

    def _atomic_write_env_value(self, raw_value: str) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                prefix=".ankey_vault_keyring_",
                suffix=".tmp",
                dir=self._path.parent,
                delete=False,
            ) as temp_file:
                temp_path = Path(temp_file.name)
                temp_file.write(f"{self._env_var}={raw_value}\n")
                temp_file.flush()
                os.fsync(temp_file.fileno())
                os.fchmod(temp_file.fileno(), 0o600)

            os.replace(temp_path, self._path)
            os.chmod(self._path, 0o600)
            _fsync_directory(self._path.parent)
        except OSError as exc:
            raise SecretStoreError(
                "Failed to persist managed vault env keyring",
                details={
                    "reason": "managed_env_write_failed",
                    "path": str(self._path),
                    "errno": getattr(exc, "errno", None),
                    "env_var": self._env_var,
                },
            ) from exc
        finally:
            if temp_path is not None and temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    # Очистка временного файла в режиме "по возможности".
                    pass


def _extract_env_value(line: str, *, env_var: str) -> str | None:
    """Извлечь значение env-переменной из одной строки dotenv/shell формата."""
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if stripped.startswith("export "):
        stripped = stripped[len("export "):].strip()
    key, sep, value = stripped.partition("=")
    if sep != "=":
        return None
    if key.strip() != env_var:
        return None
    return _strip_optional_quotes(value.strip())


def _strip_optional_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
