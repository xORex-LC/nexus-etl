from __future__ import annotations

import csv
import re
from typing import Iterable

from connector.domain.models import ValidationErrorItem
from connector.domain.transform.result import TransformResult
from connector.domain.transform.source_record import SourceRecord
from connector.infra.sources.csv_utils import CsvFormatError, parseNull
from connector.datasets.employees.field_rules import FIELD_RULES

EXPECTED_COLUMNS = 14
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

_EMAIL_RE = re.compile(r"[^\s,;|]+@[^\s,;|]+")
_PHONE_RE = re.compile(r"[+\d][\d\s()\-]{5,}")
_MANAGER_ID_RE = re.compile(r"(?:manager_id|manager)\s*[:=]\s*([^;]+)", re.IGNORECASE)


def _to_canonical_keys(values: dict[str, object]) -> dict[str, object]:
    return {
        "email": values.get("email"),
        "last_name": values.get("lastName"),
        "first_name": values.get("firstName"),
        "middle_name": values.get("middleName"),
        "is_logon_disable": values.get("isLogonDisable"),
        "user_name": values.get("userName"),
        "phone": values.get("phone"),
        "password": values.get("password"),
        "personnel_number": values.get("personnelNumber"),
        "manager_id": values.get("managerId"),
        "organization_id": values.get("organization_id"),
        "position": values.get("position"),
        "avatar_id": values.get("avatarId"),
        "usr_org_tab_num": values.get("usrOrgTabNum"),
    }


class NormalizedEmployeesCsvRecordSource:
    """
    Назначение/ответственность:
        Источник TransformResult для нормализованного employees CSV.
    """

    def __init__(self, path: str, has_header: bool):
        self.path = path
        self.has_header = has_header

    def __iter__(self) -> Iterable[TransformResult[None]]:
        with open(self.path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f, delimiter=";")
            data_line_no = 0
            for csv_line_no, row in enumerate(reader, start=1):
                if csv_line_no == 1 and self.has_header:
                    continue
                if len(row) == 0 or (len(row) == 1 and row[0].strip() == ""):
                    continue
                data_line_no += 1
                if len(row) != EXPECTED_COLUMNS:
                    raise CsvFormatError(
                        f"Invalid column count at line {csv_line_no}: expected {EXPECTED_COLUMNS}, got {len(row)}"
                    )
                values_raw = [parseNull(v) for v in row]
                errors: list[ValidationErrorItem] = []
                warnings: list[ValidationErrorItem] = []
                values: dict[str, object] = {}
                for rule in FIELD_RULES:
                    values[rule.name] = rule.apply(values_raw, errors, warnings)

                record = SourceRecord(
                    line_no=csv_line_no,
                    record_id=f"line:{csv_line_no}",
                    values=_to_canonical_keys(values),
                )
                yield TransformResult(
                    record=record,
                    row=None,
                    row_ref=None,
                    match_key=None,
                    errors=errors,
                    warnings=warnings,
                )


class SourceEmployeesCsvRecordSource:
    """
    Назначение/ответственность:
        Источник TransformResult для source-формата employees CSV.
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
            data_line_no = 0
            for csv_line_no, row in enumerate(reader, start=2 if self.has_header else 1):
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

                if len(values) != EXPECTED_COLUMNS:
                    raise CsvFormatError(
                        f"Invalid column count at line {csv_line_no}: expected {EXPECTED_COLUMNS}, got {len(values)}"
                    )

                record = SourceRecord(
                    line_no=csv_line_no,
                    record_id=f"line:{csv_line_no}",
                    values=_to_canonical_keys(
                        {
                            "email": values[0],
                            "lastName": values[1],
                            "firstName": values[2],
                            "middleName": values[3],
                            "isLogonDisable": values[4],
                            "userName": values[5],
                            "phone": values[6],
                            "password": values[7],
                            "personnelNumber": values[8],
                            "managerId": values[9],
                            "organization_id": values[10],
                            "position": values[11],
                            "avatarId": values[12],
                            "usrOrgTabNum": values[13],
                        }
                    ),
                )
                yield TransformResult(
                    record=record,
                    row=None,
                    row_ref=None,
                    match_key=None,
                    errors=[],
                    warnings=[],
                )


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
    digits = re.findall(r"\d+", manager)
    if not digits:
        return None
    return digits[0]


def _parse_disabled(flags: str | None) -> str | None:
    if not flags:
        return None
    match = re.search(r"disabled\s*[:=]\s*([^;]+)", flags, re.IGNORECASE)
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
    match = re.search(r"role\s*[:=]\s*([^;]+)", employment, re.IGNORECASE)
    if match:
        return _normalize(match.group(1))
    return None
