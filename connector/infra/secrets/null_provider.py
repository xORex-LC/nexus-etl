from __future__ import annotations

from connector.domain.ports.secrets import SecretProviderProtocol


class NullSecretProvider(SecretProviderProtocol):
    """
    Назначение:
        Реализация-пустышка: никогда не возвращает секрет.
    Паттерн:
        Null Object.
    """

    def get_secret(
        self,
        *,
        dataset: str,
        field: str,
        row_id: str | None = None,
        line_no: int | None = None,
        source_ref: dict | None = None,
        target_id: str | None = None,
        run_id: str | None = None,
    ) -> str | None:
        return None
