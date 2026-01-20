from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, Tuple


@dataclass
class RequestSpec:
    """
    Назначение/ответственность:
        Описывает инструкцию для выполнения внешнего запроса без привязки к HTTP-клиенту.
    Инварианты/гарантии:
        - method и path заданы явно.
        - expected_statuses задаёт допустимые коды ответа (может быть пустым).
    Взаимодействия:
        Передаётся в RequestExecutorProtocol.execute().
    """

    method: str
    path: str
    json: Any | None = None
    query: dict[str, str] | None = None
    headers: dict[str, str] | None = None
    expected_statuses: Tuple[int, ...] = field(default_factory=tuple)
    idempotency_key: str | None = None


@dataclass
class ExecutionResult:
    """
    Назначение/ответственность:
        Нормализованный результат выполнения RequestSpec.
    Инварианты/гарантии:
        - ok отражает успешность согласно исполнителю.
        - attempts >= 1, duration_ms >= 0 (если заполнено).
    Взаимодействия:
        Возвращается исполнителем в ответ на execute().
    """

    ok: bool
    status_code: int | None = None
    error_code: str | None = None
    error_message: str | None = None
    attempts: int = 1
    duration_ms: int | None = None
    response_json: Any | None = None


class RequestExecutorProtocol(Protocol):
    """
    Назначение/ответственность:
        Порт выполнения внешних запросов по спецификации RequestSpec.
    Взаимодействия:
        Реализации инкапсулируют детали HTTP/ретраев/логирования;
        use-case зависит только от протокола.
    Ограничения:
        Синхронное выполнение, одна спецификация за вызов.
    """

    def execute(self, request: RequestSpec) -> ExecutionResult:
        """
        Контракт (вход/выход):
            - Вход: RequestSpec.
            - Выход: ExecutionResult с признаком ok и деталями ответа.
        Ошибки/исключения:
            Реализации могут пробрасывать инфраструктурные ошибки,
            либо всегда возвращать ExecutionResult в состоянии ошибки.
        """
        ...
