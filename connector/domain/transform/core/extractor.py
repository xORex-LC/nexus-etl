"""
Назначение:
    Extract-стадия: чтение источника в SourceRecord.
"""

from __future__ import annotations

from typing import Iterable

from connector.domain.models import DiagnosticStage, RowRef
from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.diagnostics.context import error as diag_error
from connector.domain.ports.transform.sources import RowSource
from connector.domain.transform.core.result import TransformResult
from connector.domain.transform.core.source_record import SourceRecord


class Extractor:
    """
    Назначение/ответственность:
        Унифицированное ядро извлечения: оборачивает SourceRecord в TransformResult
        и фиксирует фатальные ошибки источника как EXTRACT-диагностику.
    """

    def __init__(self, source: RowSource, catalog: ErrorCatalog) -> None:
        self.source = source
        self.catalog = catalog

    def run(self) -> Iterable[TransformResult[None]]:
        """
        Назначение:
            Считать источник и обернуть записи в TransformResult.

        Алгоритм:
            - Каждую запись источника возвращает как TransformResult без row.
            - Любая ошибка источника фиксируется как EXTRACT‑ошибка.
        """
        try:
            for record in self.source:
                yield TransformResult(
                    record=record,
                    row=None,
                    row_ref=None,
                    match_key=None,
                    errors=[],
                    warnings=[],
                )
        except Exception as exc:  # noqa: BLE001
            row_ref = RowRef(
                line_no=0,
                row_id="source",
                identity_primary=None,
                identity_value=None,
            )
            error = diag_error(
                catalog=self.catalog,
                stage=DiagnosticStage.EXTRACT,
                code="SOURCE_ERROR",
                field=None,
                message=str(exc),
                record_ref=row_ref,
            )
            yield TransformResult(
                record=SourceRecord(line_no=0, record_id="source", values={}),
                row=None,
                row_ref=row_ref,
                match_key=None,
                errors=(error,),
                warnings=(),
            )
