from __future__ import annotations

import csv
from typing import Iterator

from .models import CsvRow

EXPECTED_COLUMNS = 14

class CsvFormatError(Exception):
    """
    Назначение:
        Ошибка критического формата CSV (количество колонок и т.п.).
    """

def parseNull(value: str | None) -> str | None:
    """
    Назначение:
        Преобразует пустые/NULL значения в None и тримит строки.
    """
    if value is None:
        return None
    trimmed = value.strip()
    if trimmed == "" or trimmed.lower() == "null":
        return None
    return trimmed

def readEmployeeRows(csvPath: str, hasHeader: bool) -> Iterator[CsvRow]:
    """
    Назначение:
        Читает CSV построчно, нормализует значения и валидирует число колонок.
    """
    with open(csvPath, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f, delimiter=";")
        data_line_no = 0
        for csv_line_no, row in enumerate(reader, start=1):
            if csv_line_no == 1 and hasHeader:
                continue
            if len(row) == 0 or (len(row) == 1 and row[0].strip() == ""):
                continue
            data_line_no += 1
            if len(row) != EXPECTED_COLUMNS:
                raise CsvFormatError(
                    f"Invalid column count at line {csv_line_no}: expected {EXPECTED_COLUMNS}, got {len(row)}"
                )
            values = [parseNull(v) for v in row]
            yield CsvRow(file_line_no=csv_line_no, data_line_no=data_line_no, values=values)
