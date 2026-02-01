from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from connector.domain.diagnostics.exceptions import OperationError, UnknownDiagnosticCodeError
from connector.domain.diagnostics.context import error as diag_error
from connector.domain.diagnostics.translator import Translator
from connector.domain.models import DiagnosticStage, RowRef


@contextmanager
def diagnostic_boundary(
    stage: DiagnosticStage,
    translator: Translator,
    sink: list,
    record_ref: RowRef | None = None,
) -> Iterator[None]:
    """
    Назначение:
        Boundary для единообразной обработки ошибок и преобразования их в DiagnosticItem.

    Контракт:
        - OperationError превращается в DiagnosticItem через DiagnosticFactory.
        - Неожиданные исключения преобразуются translator'ом.
        - Все созданные диагностические события добавляются в sink.
    """
    try:
        yield
    except OperationError as exc:
        sink.append(
            diag_error(
                stage=exc.stage,
                code=exc.code,
                field=exc.field,
                message=exc.message,
                record_ref=exc.record_ref,
                details=exc.details,
            )
        )
    except UnknownDiagnosticCodeError:
        # В strict-режиме неизвестный код должен падать, а не маскироваться.
        raise
    except Exception as exc:  # pragma: no cover - защитная ветка
        sink.append(translator.from_exception(stage, exc, record_ref=record_ref))
