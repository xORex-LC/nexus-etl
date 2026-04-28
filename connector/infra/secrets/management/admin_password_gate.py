"""Назначение:
    Password-gate для операций vault-management.

Граница ответственности:
    - Проверяет доступ администратора по паролю и argon2id-хешу из managed
      hash-файла или legacy ENV-источника.
    - Проверяет filesystem-права hash-файла перед использованием.
    - Поддерживает interactive и non-interactive режимы получения пароля.
    - Логирует только безопасную операционную телеметрию (без secret/hash leakage).
    - Не выполняет orchestration lifecycle-операций и не управляет keyring/БД.
"""

from __future__ import annotations

import getpass
import os
import stat
from collections.abc import Callable, Mapping
from pathlib import Path

import structlog
from argon2 import PasswordHasher, exceptions as argon2_exceptions
from argon2.exceptions import VerifyMismatchError

from connector.domain.secrets.errors import (
    VaultAdminAccessDeniedError,
    VaultAdminPasswordConfigError,
)

PromptFn = Callable[[str], str]

# Динамическое построение кортежей типов исключений для совместимости
# с разными версиями argon2-cffi:
#   - argon2-cffi >=21.1: argon2.exceptions.InvalidHash
#   - argon2-cffi >=23.1: argon2.exceptions.InvalidHashError
# getattr + isinstance guard позволяет работать с обеими версиями.
_INVALID_HASH_ERRORS: tuple[type[Exception], ...] = tuple(
    exc_type
    for exc_type in (
        getattr(argon2_exceptions, "InvalidHashError", None),
        getattr(argon2_exceptions, "InvalidHash", None),
    )
    if isinstance(exc_type, type) and issubclass(exc_type, Exception)
)
_VERIFICATION_ERRORS: tuple[type[Exception], ...] = tuple(
    exc_type
    for exc_type in (
        getattr(argon2_exceptions, "VerificationError", None),
        getattr(argon2_exceptions, "VerifyMismatchError", None),
    )
    if isinstance(exc_type, type) and issubclass(exc_type, Exception)
)

# Маркеры сообщений для fallback-детекции невалидного hash.
# Покрывают argon2-cffi >=21.1 (InvalidHash message variants)
# и >=23.1 (InvalidHashError / VerificationError message variants).
_INVALID_HASH_MESSAGE_MARKERS: tuple[str, ...] = (
    "decoding failed",
    "invalid",
    "malformed",
    "hash",
)


def _is_probable_invalid_hash_error(error: Exception) -> bool:
    """Определить, что ошибка верификации вызвана некорректным hash-значением."""
    message = str(error).strip().lower()
    if not message:
        return False
    return any(marker in message for marker in _INVALID_HASH_MESSAGE_MARKERS)


class VaultAdminPasswordGate:
    """Назначение:
        Проверить доступ к vault-management операциям.

    Инварианты:
        - При `require_admin_password_for_manual_ops=False` проверка пропускается.
        - Если задан `admin_password_hash_file`, hash берётся из него и файл
          обязан быть доступен только владельцу (`0600` или строже).
        - Если hash-файл не задан, поддерживается legacy ENV-источник
          `admin_password_hash_env_var`.
        - Поддерживаются только hash-строки с префиксом `$argon2id$`.
        - Пароль не логируется и не добавляется в details исключений.
    """

    def __init__(
        self,
        *,
        require_admin_password_for_manual_ops: bool,
        admin_password_hash_env_var: str,
        admin_password_env_var: str,
        admin_password_hash_file: str | None = None,
        env: Mapping[str, str] | None = None,
        prompt_password: PromptFn | None = None,
        password_hasher: PasswordHasher | None = None,
    ) -> None:
        self._require_admin_password_for_manual_ops = require_admin_password_for_manual_ops
        self._admin_password_hash_file = admin_password_hash_file
        self._admin_password_hash_env_var = admin_password_hash_env_var
        self._admin_password_env_var = admin_password_env_var
        self._env = env if env is not None else os.environ
        self._prompt_password = prompt_password or getpass.getpass
        self._password_hasher = password_hasher or PasswordHasher()
        self._logger = structlog.get_logger(__name__)

    def verify_manual_access(self, non_interactive: bool) -> None:
        """Назначение:
            Выполнить policy-aware проверку доступа для vault-management операции.

        Контракт:
            - `non_interactive=True`: пароль читается из `admin_password_env_var`.
            - `non_interactive=False`: пароль запрашивается через prompt.
            - Hash читается из configured hash-файла, если он задан, иначе из
              legacy ENV-источника.
            - При неуспехе выбрасывает `VaultAdminPasswordConfigError` или
              `VaultAdminAccessDeniedError`.
        """
        mode = "non_interactive" if non_interactive else "interactive"
        if not self._require_admin_password_for_manual_ops:
            self._logger.info(
                "vault_admin_password_gate_skipped",
                reason="policy_disabled",
                mode=mode,
            )
            return

        password_hash = self._read_password_hash(mode=mode)
        password = self._read_password(non_interactive=non_interactive, mode=mode)
        try:
            self._verify_password(password_hash=password_hash, password=password, mode=mode)
        finally:
            password = ""

        self._logger.info("vault_admin_password_gate_passed", mode=mode)

    def _read_password_hash(self, *, mode: str) -> str:
        if self._admin_password_hash_file is not None:
            raw_hash = VaultAdminPasswordHashStore(
                hash_file=self._admin_password_hash_file,
                env_var=self._admin_password_hash_env_var,
            ).load_hash(mode=mode)
            return self._validate_password_hash(raw_hash=raw_hash, mode=mode, source="file")

        raw_hash = self._env.get(self._admin_password_hash_env_var)
        if raw_hash is None or not raw_hash.strip():
            self._logger.warning(
                "vault_admin_password_gate_failed",
                reason="admin_password_hash_missing",
                mode=mode,
                hash_env_var=self._admin_password_hash_env_var,
            )
            raise VaultAdminPasswordConfigError(
                "Vault admin password hash is missing",
                details={
                    "reason": "admin_password_hash_missing",
                    "mode": mode,
                    "hash_env_var": self._admin_password_hash_env_var,
                },
            )

        return self._validate_password_hash(raw_hash=raw_hash, mode=mode, source="env")

    def _validate_password_hash(self, *, raw_hash: str, mode: str, source: str) -> str:
        normalized_hash = raw_hash.strip()
        if not normalized_hash.startswith("$argon2id$"):
            self._logger.warning(
                "vault_admin_password_gate_failed",
                reason="unsupported_hash_algorithm",
                mode=mode,
                hash_env_var=self._admin_password_hash_env_var,
                hash_source=source,
            )
            raise VaultAdminPasswordConfigError(
                "Vault admin password hash must be argon2id",
                details={
                    "reason": "unsupported_hash_algorithm",
                    "mode": mode,
                    "hash_env_var": self._admin_password_hash_env_var,
                    "hash_source": source,
                    "required_algorithm": "argon2id",
                },
            )
        return normalized_hash

    def _read_password(self, *, non_interactive: bool, mode: str) -> str:
        if non_interactive:
            value = self._env.get(self._admin_password_env_var)
            if value is None or value == "":
                self._logger.warning(
                    "vault_admin_password_gate_failed",
                    reason="admin_password_missing",
                    mode=mode,
                    password_env_var=self._admin_password_env_var,
                )
                raise VaultAdminPasswordConfigError(
                    "Vault admin password is missing in non-interactive mode",
                    details={
                        "reason": "admin_password_missing",
                        "mode": mode,
                        "password_env_var": self._admin_password_env_var,
                    },
                )
            return value

        try:
            value = self._prompt_password("Введите пароль доступа к vault: ")
        except Exception as exc:  # pragma: no cover - зависит от TTY/runtime окружения.
            self._logger.warning(
                "vault_admin_password_gate_failed",
                reason="password_prompt_failed",
                mode=mode,
                error_type=type(exc).__name__,
            )
            raise VaultAdminAccessDeniedError(
                "Vault admin password prompt failed",
                details={"reason": "password_prompt_failed", "mode": mode},
            ) from exc

        if value == "":
            self._logger.warning(
                "vault_admin_password_gate_failed",
                reason="empty_password_input",
                mode=mode,
            )
            raise VaultAdminAccessDeniedError(
                "Vault admin password cannot be empty",
                details={"reason": "empty_password_input", "mode": mode},
            )
        return value

    def _verify_password(self, *, password_hash: str, password: str, mode: str) -> None:
        try:
            self._password_hasher.verify(password_hash, password)
        except VerifyMismatchError as exc:
            self._logger.warning(
                "vault_admin_password_gate_failed",
                reason="password_mismatch",
                mode=mode,
            )
            raise VaultAdminAccessDeniedError(
                "Vault admin password is invalid",
                details={"reason": "password_mismatch", "mode": mode},
            ) from exc
        except Exception as exc:
            if _INVALID_HASH_ERRORS and isinstance(exc, _INVALID_HASH_ERRORS):
                self._logger.warning(
                    "vault_admin_password_gate_failed",
                    reason="invalid_password_hash",
                    mode=mode,
                    hash_env_var=self._admin_password_hash_env_var,
                )
                raise VaultAdminPasswordConfigError(
                    "Vault admin password hash is invalid",
                    details={
                        "reason": "invalid_password_hash",
                        "mode": mode,
                        "hash_env_var": self._admin_password_hash_env_var,
                    },
                ) from exc
            if _VERIFICATION_ERRORS and isinstance(exc, _VERIFICATION_ERRORS):
                if _is_probable_invalid_hash_error(exc):
                    self._logger.warning(
                        "vault_admin_password_gate_failed",
                        reason="invalid_password_hash",
                        mode=mode,
                        hash_env_var=self._admin_password_hash_env_var,
                        error_type=type(exc).__name__,
                    )
                    raise VaultAdminPasswordConfigError(
                        "Vault admin password hash is invalid",
                        details={
                            "reason": "invalid_password_hash",
                            "mode": mode,
                            "hash_env_var": self._admin_password_hash_env_var,
                        },
                    ) from exc
                self._logger.warning(
                    "vault_admin_password_gate_failed",
                    reason="password_verification_failed",
                    mode=mode,
                    error_type=type(exc).__name__,
                )
                raise VaultAdminAccessDeniedError(
                    "Vault admin password verification failed",
                    details={
                        "reason": "password_verification_failed",
                        "mode": mode,
                    },
                ) from exc

            self._logger.error(
                "vault_admin_password_gate_failed",
                reason="password_verification_internal_error",
                mode=mode,
                error_type=type(exc).__name__,
            )
            raise VaultAdminAccessDeniedError(
                "Vault admin password verification failed",
                details={"reason": "password_verification_internal_error", "mode": mode},
            ) from exc


class VaultAdminPasswordHashStore:
    """Назначение:
        Прочитать argon2id hash из локального managed env-файла.

    Контракт:
        - Файл имеет dotenv/shell-like формат и содержит переменную `env_var`.
        - POSIX-права не должны давать доступ group/other (`0600`, `0400` и т.п.).
        - Значение hash не логируется и не попадает в exception details.
    """

    def __init__(self, *, hash_file: str, env_var: str) -> None:
        self._path = Path(hash_file)
        self._env_var = env_var
        self._logger = structlog.get_logger(__name__)

    def load_hash(self, *, mode: str) -> str:
        """Загрузить hash из файла после проверки существования и прав."""
        self._ensure_private_file(mode=mode)
        try:
            content = self._path.read_text(encoding="utf-8")
        except OSError as exc:
            self._logger.warning(
                "vault_admin_password_gate_failed",
                reason="admin_password_hash_file_read_failed",
                mode=mode,
                hash_file=str(self._path),
                hash_env_var=self._env_var,
                errno=getattr(exc, "errno", None),
            )
            raise VaultAdminPasswordConfigError(
                "Vault admin password hash file cannot be read",
                details={
                    "reason": "admin_password_hash_file_read_failed",
                    "mode": mode,
                    "hash_file": str(self._path),
                    "hash_env_var": self._env_var,
                    "errno": getattr(exc, "errno", None),
                },
            ) from exc

        for raw_line in content.splitlines():
            value = _extract_env_value(raw_line, env_var=self._env_var)
            if value is not None and value.strip():
                return value

        self._logger.warning(
            "vault_admin_password_gate_failed",
            reason="admin_password_hash_missing",
            mode=mode,
            hash_file=str(self._path),
            hash_env_var=self._env_var,
        )
        raise VaultAdminPasswordConfigError(
            "Vault admin password hash is missing",
            details={
                "reason": "admin_password_hash_missing",
                "mode": mode,
                "hash_file": str(self._path),
                "hash_env_var": self._env_var,
            },
        )

    def _ensure_private_file(self, *, mode: str) -> None:
        try:
            st = self._path.stat()
        except OSError as exc:
            self._logger.warning(
                "vault_admin_password_gate_failed",
                reason="admin_password_hash_file_missing",
                mode=mode,
                hash_file=str(self._path),
                hash_env_var=self._env_var,
                errno=getattr(exc, "errno", None),
            )
            raise VaultAdminPasswordConfigError(
                "Vault admin password hash file does not exist",
                details={
                    "reason": "admin_password_hash_file_missing",
                    "mode": mode,
                    "hash_file": str(self._path),
                    "hash_env_var": self._env_var,
                    "errno": getattr(exc, "errno", None),
                },
            ) from exc

        if not stat.S_ISREG(st.st_mode):
            self._logger.warning(
                "vault_admin_password_gate_failed",
                reason="admin_password_hash_file_not_regular",
                mode=mode,
                hash_file=str(self._path),
                hash_env_var=self._env_var,
            )
            raise VaultAdminPasswordConfigError(
                "Vault admin password hash path must be a regular file",
                details={
                    "reason": "admin_password_hash_file_not_regular",
                    "mode": mode,
                    "hash_file": str(self._path),
                    "hash_env_var": self._env_var,
                },
            )

        permissions = stat.S_IMODE(st.st_mode)
        if permissions & 0o077:
            self._logger.warning(
                "vault_admin_password_gate_failed",
                reason="admin_password_hash_file_permissions_too_open",
                mode=mode,
                hash_file=str(self._path),
                hash_env_var=self._env_var,
                file_mode=oct(permissions),
            )
            raise VaultAdminPasswordConfigError(
                "Vault admin password hash file permissions are too open",
                details={
                    "reason": "admin_password_hash_file_permissions_too_open",
                    "mode": mode,
                    "hash_file": str(self._path),
                    "hash_env_var": self._env_var,
                    "file_mode": oct(permissions),
                    "required": "0600 or stricter",
                },
            )


def _extract_env_value(line: str, *, env_var: str) -> str | None:
    """Извлечь значение env-переменной из одной строки dotenv/shell формата."""
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if stripped.startswith("export "):
        stripped = stripped[len("export ") :].strip()
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


__all__ = ["VaultAdminPasswordGate", "VaultAdminPasswordHashStore"]
