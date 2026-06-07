"""Observability artifact viewer — resolve latest artifact path and read file content.

Модуль даёт read-side adapter для `obs latest|tail`: он берёт последний запуск
из ledger, разрешает путь нужного артефакта и читает его содержимое с диска.

Границы ответственности:
    - Разрешать путь последнего log/report/plan через ledger.
    - Читать полный текст артефакта или хвост последних строк.

Вне ответственности:
    - CLI formatting и печать результата.
    - Публикация latest pointers и запись новых ledger entries.
"""

from __future__ import annotations

from pathlib import Path

from connector.common.observability import (
    ObservabilityArtifactKind,
    ServiceComponent,
)
from connector.infra.observability.ledger import RunLedgerBackend, RunLedgerRecord


class ObservabilityArtifactViewer:
    """Read-side adapter для поиска и чтения последних observability-артефактов."""

    def __init__(self, *, ledger_backend: RunLedgerBackend) -> None:
        self._ledger_backend = ledger_backend

    def latest_record(self, *, component: ServiceComponent) -> RunLedgerRecord | None:
        """Вернуть последнюю ledger-запись компонента или `None`."""
        return self._ledger_backend.latest_record(component=component)

    def resolve_latest_artifact_path(
        self,
        *,
        component: ServiceComponent,
        artifact_kind: ObservabilityArtifactKind,
    ) -> Path | None:
        """Разрешить путь последнего артефакта указанного типа по ledger."""
        record = self.latest_record(component=component)
        if record is None:
            return None
        artifact_path = record.artifact_path(artifact_kind)
        if artifact_path is None:
            return None
        path = Path(artifact_path)
        if not path.exists() or not path.is_file():
            return None
        return path

    def read_text(self, *, path: str | Path) -> str:
        """Прочитать весь текст артефакта как UTF-8."""
        return Path(path).read_text(encoding="utf-8")

    def tail_text(self, *, path: str | Path, lines: int) -> str:
        """Прочитать последние `lines` строк файла как UTF-8 text block."""
        text = self.read_text(path=path)
        chunks = text.splitlines()
        if lines <= 0:
            return ""
        return "\n".join(chunks[-lines:])


__all__ = ["ObservabilityArtifactViewer"]
