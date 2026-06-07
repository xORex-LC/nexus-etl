"""Log redaction engine — единый defense-in-depth слой для observability-логов

Модуль хранит общий redaction-движок для logging-подсистемы. Он умеет
маскировать структурированные поля по ключу и строковые фрагменты по regex,
чтобы один и тот же policy-источник применялся к structlog event_dict,
traceback, foreign-логам и перехваченным stdout/stderr строкам.

Границы ответственности:
    - Преобразовывать policy value-object в исполняемый redaction engine.
    - Маскировать mapping/list/scalar структуры рекурсивно.
    - Давать structlog-compatible processor для общей processor-цепочки.

Вне ответственности:
    - Загрузка конфигурации observability из YAML/ENV.
    - Решение, когда именно вызывать redaction в runtime orchestration.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final
from collections.abc import MutableMapping

from connector.common.observability import ObservabilityRedactionPolicy

_REDACTED: Final[str] = "***"


def _compile_text_patterns(keys: tuple[str, ...]) -> tuple[re.Pattern[str], ...]:
    compiled: list[re.Pattern[str]] = []
    for key in keys:
        escaped = re.escape(key)
        compiled.append(
            re.compile(
                rf'(?i)("?(?:{escaped})"?\s*[:=]\s*")([^"\n]*)(")',
            )
        )
        compiled.append(
            re.compile(
                rf"(?i)\b({escaped})\b(\s*[:=]\s*)([^\s,;]+)",
            )
        )
    return tuple(compiled)


@dataclass(frozen=True)
class LogRedactionEngine:
    """Маскировать чувствительные значения во всех log-surface одной политикой.

    Движок не знает о logger backend и работает с обычными Python-значениями:
    dict/list/scalar. Для строк поддерживаются regex-замены по секретным ключам,
    чтобы редактирование срабатывало и на plaintext сообщениях.
    """

    policy: ObservabilityRedactionPolicy
    replacement: str = _REDACTED
    _normalized_keys: frozenset[str] = field(init=False, repr=False)
    _patterns: tuple[re.Pattern[str], ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        normalized_keys = frozenset(
            key.casefold() for key in self.policy.keys if key.strip()
        )
        object.__setattr__(self, "_normalized_keys", normalized_keys)
        object.__setattr__(
            self, "_patterns", _compile_text_patterns(tuple(normalized_keys))
        )

    def redact_text(self, value: str) -> str:
        """Вернуть строку с замаскированными секретами."""
        if not self.policy.enabled or not value:
            return value

        redacted = value
        for pattern in self._patterns:
            redacted = pattern.sub(self._replace_match, redacted)
        return redacted

    def redact_value(self, value: Any, *, key: str | None = None) -> Any:
        """Рекурсивно замаскировать значение по ключу и строковым паттернам."""
        if not self.policy.enabled:
            return value
        if key is not None and key.casefold() in self._normalized_keys:
            return self.replacement
        if isinstance(value, Mapping):
            return {
                item_key: self.redact_value(item_value, key=str(item_key))
                for item_key, item_value in value.items()
            }
        if isinstance(value, Sequence) and not isinstance(
            value, (str, bytes, bytearray)
        ):
            return [self.redact_value(item) for item in value]
        if isinstance(value, str):
            return self.redact_text(value)
        return value

    def redact_event_dict(self, event_dict: Mapping[str, Any]) -> dict[str, Any]:
        """Применить redaction к structlog event_dict."""
        return {
            key: self.redact_value(value, key=key) for key, value in event_dict.items()
        }

    def processor(
        self,
        _logger: Any,
        _method_name: str,
        event_dict: MutableMapping[str, Any],
    ) -> Mapping[str, Any]:
        """Structlog processor, применяющий redaction к event_dict."""
        return self.redact_event_dict(event_dict)

    def _replace_match(self, match: re.Match[str]) -> str:
        groups = match.groups()
        if len(groups) == 3:
            if groups[0].startswith('"') or groups[0].endswith('"'):
                prefix, _secret, suffix = groups
                return f"{prefix}{self.replacement}{suffix}"
            key, separator, _secret = groups
            return f"{key}{separator}{self.replacement}"
        return match.group(0)


__all__ = ["LogRedactionEngine"]
