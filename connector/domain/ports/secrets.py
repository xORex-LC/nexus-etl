from __future__ import annotations

from typing import Protocol


class SecretProviderProtocol(Protocol):
    """
    Назначение:
        Порт для получения чувствительных данных (секретов) по контексту планового элемента.
    Взаимодействия:
        Вызывается адаптерами apply, чтобы дополнить RequestSpec недостающими секретами.
    Ограничения:
        Не знает о конкретных источниках (CLI/файлы/хранилище) — только о контракте.
    """

    def get_secret(
        self,
        *,
        dataset: str,
        field: str,
        row_id: str | None = None,
        line_no: int | None = None,
        source_ref: dict | None = None,
        resource_id: str | None = None,
        run_id: str | None = None,
    ) -> str | None:
        """
        Контракт (вход/выход):
            - Вход: контекст планового элемента (dataset, поле, идентификаторы).
            - Выход: строка-секрет или None, если секрет недоступен.
        Ошибки/исключения:
            Реализации могут выбрасывать свои исключения (например, проблемы доступа к хранилищу),
            но не должны скрывать сам факт отсутствия секрета — для этого возвращается None.
        """
        ...


__all__ = ["SecretProviderProtocol"]
