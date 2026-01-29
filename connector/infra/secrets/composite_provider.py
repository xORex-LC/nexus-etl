from __future__ import annotations

from typing import Iterable

from connector.domain.ports.secrets import SecretProviderProtocol


class CompositeSecretProvider(SecretProviderProtocol):
    """
    Назначение:
        Объединяет несколько провайдеров и возвращает первый найденный секрет.
    Паттерн:
        Composite / Chain of Responsibility.
    """

    def __init__(self, providers: Iterable[SecretProviderProtocol]):
        self._providers = list(providers)

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
        for provider in self._providers:
            value = provider.get_secret(
                dataset=dataset,
                field=field,
                row_id=row_id,
                line_no=line_no,
                source_ref=source_ref,
                target_id=target_id,
                run_id=run_id,
            )
            if value is not None:
                return value
        return None
