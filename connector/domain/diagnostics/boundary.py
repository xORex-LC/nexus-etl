"""
Назначение:
    Boundary для нормализации исключений в диагностические события.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.diagnostics.exceptions import UnknownDiagnosticCodeError
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
        - Неожиданные исключения преобразуются translator-функциями.
        - Все созданные диагностические события добавляются в sink.
    """
    try:
        yield
    except UnknownDiagnosticCodeError:
        # В strict-режиме неизвестный код должен падать, а не маскироваться.
        raise
    except Exception as exc:  # pragma: no cover - защитная ветка
        sink.append(translate_exception(catalog, stage, exc, record_ref=record_ref))
