from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from connector.domain.diagnostics.catalog import ErrorCatalog, build_error
from connector.domain.diagnostics.exceptions import OperationError, UnknownDiagnosticCodeError
from connector.domain.diagnostics.translator import translate_exception
from connector.domain.models import DiagnosticStage, RowRef


@contextmanager
def diagnostic_boundary(
    stage: DiagnosticStage,
    catalog: ErrorCatalog,
    sink: list,
    record_ref: RowRef | None = None,
) -> Iterator[None]:
    """
    Назначение:
        Boundary для единообразной обработки ошибок и преобразования их в DiagnosticItem.

    Контракт:
        - OperationError превращается в DiagnosticItem через ErrorCatalog.
        - Неожиданные исключения преобразуются translator-функциями.
        - Все созданные диагностические события добавляются в sink.
    """
    try:
        yield
    except OperationError as exc:
        sink.append(
            build_error(
                catalog=catalog,
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
        sink.append(translate_exception(catalog, stage, exc, record_ref=record_ref))
