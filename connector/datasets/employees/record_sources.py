from __future__ import annotations

import csv
from typing import Iterable

from connector.domain.transform.result import TransformResult
from connector.domain.transform.source_record import SourceRecord
from connector.infra.sources.csv_utils import CsvFormatError, parseNull
SOURCE_COLUMNS = [
    "raw_id",
    "full_name",
    "login",
    "email_or_phone",
    "contacts",
    "org",
    "manager",
    "flags",
    "employment",
    "extra",
]

class EmployeesCsvRecordSource:
    """
    Назначение/ответственность:
        Источник TransformResult для source-формата employees CSV (единый формат).
    """

    def __init__(self, path: str, has_header: bool):
        self.path = path
        self.has_header = has_header

    def __iter__(self) -> Iterable[TransformResult[None]]:
        with open(self.path, "r", encoding="utf-8-sig", newline="") as f:
            fieldnames = None if self.has_header else SOURCE_COLUMNS
            reader = csv.DictReader(f, delimiter=",", fieldnames=fieldnames)
            if self.has_header and reader.fieldnames is None:
                raise CsvFormatError("Missing header in source CSV")
            if self.has_header:
                missing = [name for name in SOURCE_COLUMNS if name not in (reader.fieldnames or [])]
                if missing:
                    raise CsvFormatError(f"Missing required columns in source CSV: {', '.join(missing)}")
            for csv_line_no, row in enumerate(reader, start=2 if self.has_header else 1):
                if not row:
                    continue
                values = {key: parseNull(row.get(key)) for key in SOURCE_COLUMNS}
                record = SourceRecord(
                    line_no=csv_line_no,
                    record_id=f"line:{csv_line_no}",
                    values=values,
                )
                yield TransformResult(
                    record=record,
                    row=None,
                    row_ref=None,
                    match_key=None,
                    errors=[],
                    warnings=[],
                )
