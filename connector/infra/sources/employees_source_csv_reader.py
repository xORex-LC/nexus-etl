from __future__ import annotations

import csv
import re
from typing import Iterator

from connector.domain.models import CsvRow
from connector.domain.ports.sources import LegacyRowSource
from connector.infra.sources.csv_reader import CsvFormatError

EMPLOYEES_COLUMNS = 14
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

_EMAIL_RE = re.compile(r"[^\\s,;|]+@[^\\s,;|]+")
_PHONE_RE = re.compile(r"[+\d][\d\s()\-]{5,}")
_MANAGER_ID_RE = re.compile(r"(?:manager_id|manager)\\s*[:=]\\s*([^;]+)", re.IGNORECASE)


def _normalize(value: str | None) -> str | None:
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None


def _split_full_name(full_name: str | None) -> tuple[str | None, str | None, str | None]:
    if not full_name:
        return None, None, None
    raw = full_name.strip()
    if "," in raw:
        last, rest = raw.split(",", 1)
        parts = [p for p in rest.strip().split(" ") if p]
        first = parts[0] if parts else None
        middle = parts[1] if len(parts) > 1 else None
        return _normalize(last), _normalize(first), _normalize(middle)
    parts = [p for p in raw.split(" ") if p]
    last = parts[0] if parts else None
    first = parts[1] if len(parts) > 1 else None
    middle = parts[2] if len(parts) > 2 else None
    return _normalize(last), _normalize(first), _normalize(middle)


def _pick_email_phone(*candidates: str | None) -> tuple[str | None, str | None]:
    email = None
    phone = None
    for candidate in candidates:
        if not candidate:
            continue
        for token in re.split(r"[;|,]", candidate):
            token = token.strip()
            if not token:
                continue
            if "email=" in token.lower():
                _, value = token.split("=", 1)
                if _EMAIL_RE.search(value):
                    email = email or _normalize(value)
                    continue
            if "phone=" in token.lower():
                _, value = token.split("=", 1)
                if _PHONE_RE.search(value):
                    phone = phone or _normalize(value)
                    continue
            if _EMAIL_RE.search(token):
                email = email or _normalize(token)
                continue
            if _PHONE_RE.search(token):
                phone = phone or _normalize(token)
                continue
    return email, phone


def _parse_kv_pairs(raw: str | None) -> dict[str, str]:
    if not raw:
        return {}
    pairs = {}
    for token in raw.split(";"):
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        key = key.strip().lower()
        value = value.strip()
        if key:
            pairs[key] = value
    return pairs


def _parse_manager_id(manager: str | None) -> str | None:
    if not manager:
        return None
    match = _MANAGER_ID_RE.search(manager)
    if match:
        manager = match.group(1)
    digits = re.findall(r"\\d+", manager)
    if not digits:
        return None
    return digits[0]


def _parse_disabled(flags: str | None) -> str | None:
    if not flags:
        return None
    match = re.search(r"disabled\\s*[:=]\\s*([^;]+)", flags, re.IGNORECASE)
    if not match:
        return None
    raw = match.group(1).strip().lower()
    if raw in ("true", "1", "yes", "y", "on"):
        return "true"
    if raw in ("false", "0", "no", "n", "off"):
        return "false"
    return None


def _parse_role(employment: str | None) -> str | None:
    if not employment:
        return None
    match = re.search(r"role\\s*[:=]\\s*([^;]+)", employment, re.IGNORECASE)
    if match:
        return _normalize(match.group(1))
    return None


def readEmployeesSourceRows(csvPath: str, hasHeader: bool) -> Iterator[CsvRow]:
    """
    Назначение:
        Читает "сырые" строки source CSV и приводит к 14 колонкам Employees.
    """
    with open(csvPath, "r", encoding="utf-8-sig", newline="") as f:
        fieldnames = None if hasHeader else SOURCE_COLUMNS
        reader = csv.DictReader(f, delimiter=",", fieldnames=fieldnames)
        if hasHeader and reader.fieldnames is None:
            raise CsvFormatError("Missing header in source CSV")
        data_line_no = 0
        for csv_line_no, row in enumerate(reader, start=2 if hasHeader else 1):
            if not row:
                continue
            data_line_no += 1
            raw_id = _normalize(row.get("raw_id"))
            full_name = _normalize(row.get("full_name"))
            login = _normalize(row.get("login"))
            email_or_phone = _normalize(row.get("email_or_phone"))
            contacts = _normalize(row.get("contacts"))
            manager = _normalize(row.get("manager"))
            flags = _normalize(row.get("flags"))
            employment = _normalize(row.get("employment"))
            extra = _normalize(row.get("extra"))

            last_name, first_name, middle_name = _split_full_name(full_name)
            email, phone = _pick_email_phone(email_or_phone, contacts)
            manager_id = _parse_manager_id(manager)
            disabled = _parse_disabled(flags)
            position = _parse_role(employment)
            extra_pairs = _parse_kv_pairs(extra)

            values = [
                email,
                last_name,
                first_name,
                middle_name,
                disabled,
                login,
                phone,
                extra_pairs.get("password"),
                raw_id,
                manager_id,
                extra_pairs.get("org_id"),
                position,
                None,
                extra_pairs.get("tab"),
            ]

            if len(values) != EMPLOYEES_COLUMNS:
                raise CsvFormatError(
                    f"Invalid column count at line {csv_line_no}: expected {EMPLOYEES_COLUMNS}, got {len(values)}"
                )

            yield CsvRow(file_line_no=csv_line_no, data_line_no=data_line_no, values=values)


class EmployeesSourceCsvRowSource(LegacyRowSource):
    """
    Назначение/ответственность:
        Источник CsvRow на основе source CSV (анархичный формат).

    TODO: TECHDEBT - legacy reader; используйте datasets.employees.record_sources.SourceEmployeesCsvRecordSource.
    """

    def __init__(self, path: str, has_header: bool):
        self.path = path
        self.has_header = has_header

    def __iter__(self):
        return readEmployeesSourceRows(self.path, self.has_header)
