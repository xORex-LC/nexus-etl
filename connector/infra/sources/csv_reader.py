from __future__ import annotations

import csv
from typing import Iterable

from connector.domain.transform.result import TransformResult
from connector.domain.transform.source_record import SourceRecord
from connector.infra.sources.csv_utils import CsvFormatError, parseNull


class CsvRecordSource:
    """
    Назначение/ответственность:
        Универсальный CSV-источник: читает строки и отдаёт SourceRecord без привязки к датасету.
    """

    def __init__(self, path: str, has_header: bool) -> None:
        self.path = path
        self.has_header = has_header

    def __iter__(self) -> Iterable[TransformResult[None]]:
        with open(self.path, "r", encoding="utf-8-sig", newline="") as f:
            if self.has_header:
                reader = csv.DictReader(f, delimiter=",")
                if reader.fieldnames is None:
                    raise CsvFormatError("Missing header in source CSV")
                for csv_line_no, row in enumerate(reader, start=2):
                    if not row:
                        continue
                    if None in row:
                        extra = row.get(None) or []
                        got = len(reader.fieldnames) + len(extra)
                        raise CsvFormatError(
                            f"Invalid column count at line {csv_line_no}: expected {len(reader.fieldnames)}, got {got}"
                        )
                    values = {key: parseNull(row.get(key)) for key in row}
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
                return

            reader = csv.reader(f, delimiter=",")
            expected_len: int | None = None
            for csv_line_no, row in enumerate(reader, start=1):
                if not row:
                    continue
                if expected_len is None:
                    expected_len = len(row)
                elif len(row) != expected_len:
                    raise CsvFormatError(
                        f"Invalid column count at line {csv_line_no}: expected {expected_len}, got {len(row)}"
                    )
                values = {f"col_{idx}": parseNull(value) for idx, value in enumerate(row)}
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
