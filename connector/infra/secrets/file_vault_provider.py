from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable

from connector.common.time import getNowIso
from connector.domain.ports.secrets import SecretProviderProtocol, SecretStoreProtocol


_FIELDNAMES = ["dataset", "field", "match_key", "value", "run_id", "updated_at"]


class FileVaultSecretStore(SecretStoreProtocol):
    """
    Назначение:
        Запись секретов в CSV-файл (dev vault).
    """

    def __init__(self, path: str):
        self._path = Path(path)

    def put_many(
        self,
        *,
        dataset: str,
        match_key: str,
        secrets: dict[str, str],
        run_id: str | None = None,
    ) -> None:
        if not secrets:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        needs_header = not self._path.exists()
        with self._path.open("a", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=_FIELDNAMES)
            if needs_header:
                writer.writeheader()
            now = getNowIso()
            for field, value in secrets.items():
                writer.writerow(
                    {
                        "dataset": dataset,
                        "field": field,
                        "match_key": match_key,
                        "value": value,
                        "run_id": run_id or "",
                        "updated_at": now,
                    }
                )


class FileVaultSecretProvider(SecretProviderProtocol):
    """
    Назначение:
        Чтение секретов из CSV-файла (dev vault).
    """

    def __init__(self, path: str):
        self._path = Path(path)

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
        match_key = None
        if source_ref and isinstance(source_ref, dict):
            match_key = source_ref.get("match_key")
        if not match_key:
            return None
        if not self._path.exists():
            return None
        rows = _read_rows(self._path)
        best = None
        best_run = None
        for row in rows:
            if row.get("dataset") != dataset:
                continue
            if row.get("field") != field:
                continue
            if row.get("match_key") != match_key:
                continue
            row_run = row.get("run_id") or None
            if run_id and row_run == run_id:
                best = row
                best_run = row_run
                break
            best = row
            best_run = row_run
        if best is None:
            return None
        return best.get("value")


def _read_rows(path: Path) -> Iterable[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row:
                continue
            yield row
