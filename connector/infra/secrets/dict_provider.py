from __future__ import annotations

from typing import Dict, Tuple

from connector.domain.ports.secrets import SecretProviderProtocol

Key = Tuple[str, str, str | None, int | None]


class DictSecretProvider(SecretProviderProtocol):
    """
    Назначение:
        Простая in-memory реализация для тестов/ручных сценариев.
    Алгоритм:
        Ищет секрет по ключам в порядке приоритета:
        1) (dataset, field, row_id, line_no)
        2) (dataset, field, row_id, None)
        3) (dataset, field, None, line_no)
        4) (dataset, field, None, None)
    """

    def __init__(self, mapping: Dict[Key, str] | None = None):
        self._mapping: Dict[Key, str] = mapping or {}

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
        candidates: list[Key] = [
            (dataset, field, row_id, line_no),
            (dataset, field, row_id, None),
            (dataset, field, None, line_no),
            (dataset, field, None, None),
        ]
        for key in candidates:
            if key in self._mapping:
                return self._mapping[key]
        return None

    def set_secret(self, dataset: str, field: str, value: str, row_id: str | None = None, line_no: int | None = None):
        """Удобный сеттер для тестов/ручного наполнения."""
        self._mapping[(dataset, field, row_id, line_no)] = value
