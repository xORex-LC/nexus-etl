from __future__ import annotations

from typing import Iterable

from connector.domain.models import DiagnosticStage, ValidationErrorItem
from connector.domain.ports.sources import RowSource
from connector.domain.transform.result import TransformResult
from connector.domain.transform.source_record import SourceRecord


class Extractor:
    """
    Назначение/ответственность:
        Унифицированное ядро извлечения: оборачивает SourceRecord в TransformResult
        и фиксирует фатальные ошибки источника как EXTRACT-диагностику.
    """

    def __init__(self, source: RowSource) -> None:
        self.source = source

    def run(self) -> Iterable[TransformResult[None]]:
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
            error = ValidationErrorItem(
                stage=DiagnosticStage.EXTRACT,
                code="SOURCE_ERROR",
                field=None,
                message=str(exc),
            )
            yield TransformResult(
                record=SourceRecord(line_no=0, record_id="source", values={}),
                row=None,
                row_ref=None,
                match_key=None,
                errors=[error],
                warnings=[],
            )
