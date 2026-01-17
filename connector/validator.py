from __future__ import annotations

"""
Совместимость: публичные API валидации.

Содержит тонкую обёртку над новым пакетом validation/*, чтобы не переписывать
все импорты сразу.
"""

from dataclasses import dataclass
import logging
from typing import Any, Callable

from .loggingSetup import logEvent
from .models import ValidationErrorItem, ValidationRowResult
from .validation.pipeline import (
    validateEmployeeRow,
    validateEmployeeRowWithContext,
    build_match_key as buildMatchKey,
)
from .validation.row_rules import normalize_whitespace as normalizeWhitespace

@dataclass
class ValidationContext:
    """
    Назначение:
        Совместимость со старым API валидации — держатель состояния и lookup'ов.
    """

    matchkey_seen: dict[str, int]
    usr_org_tab_seen: dict[str, int]
    org_lookup: Callable[[int], Any] | None = None
    on_missing_org: str = "error"

def logValidationFailure(
    logger,
    run_id: str,
    context: str,
    result: ValidationRowResult,
    report_item_index: int | None,
    errors: list[ValidationErrorItem] | None = None,
    warnings: list[ValidationErrorItem] | None = None,
) -> None:
    """
    Назначение:
        Логирует информацию о невалидной строке CSV.

    Контракт:
        - logger: logging.Logger
        - run_id: str
        - context: str (компонент/этап)
        - result: ValidationRowResult
        - report_item_index: индекс элемента отчёта или None
        - errors/warnings: опционально явные списки ошибок/предупреждений
    """
    eff_errors = errors if errors is not None else result.errors
    eff_warnings = warnings if warnings is not None else result.warnings

    codes: list[str] = []
    codes.extend(e.code for e in eff_errors)
    codes.extend(w.code for w in eff_warnings)
    code_str = ",".join(sorted(set(codes))) if codes else "none"
    index_str = (
        str(report_item_index)
        if report_item_index is not None
        else f"line:{result.line_no} (not stored: limit reached)"
    )
    logEvent(
        logger,
        logging.WARNING,
        run_id,
        context,
        f"invalid row line={result.line_no} report_item_index={index_str} errors={code_str}",
    )

__all__ = [
    "ValidationContext",
    "validateEmployeeRow",
    "validateEmployeeRowWithContext",
    "buildMatchKey",
    "normalizeWhitespace",
    "logValidationFailure",
]