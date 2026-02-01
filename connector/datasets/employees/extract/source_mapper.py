from __future__ import annotations

from connector.domain.models import DiagnosticStage, DiagnosticItem
from connector.domain.ports.sources import SourceMapper
from connector.domain.transform.result import TransformResult
from connector.domain.transform.source_record import SourceRecord
from typing import Mapping
import re
from connector.datasets.employees.extract.models import EmployeesRowPublic
from connector.domain.validation.row_rules import normalize_whitespace
from connector.datasets.employees.extract.mapping_spec import EmployeesMappingSpec

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

SOURCE_INDEX_SCHEMA = {name: idx for idx, name in enumerate(SOURCE_COLUMNS)}


class EmployeesSourceMapper(SourceMapper[EmployeesRowPublic]):
    """
    Назначение/ответственность:
        Маппинг CSV-строки сотрудников в публичную каноническую форму.
    """

    def __init__(self, spec: EmployeesMappingSpec | None = None) -> None:
        self.spec = spec or EmployeesMappingSpec()

    def map(self, record: SourceRecord) -> TransformResult[EmployeesRowPublic]:
        errors: list[DiagnosticItem] = []
        warnings: list[DiagnosticItem] = []
        result = TransformResult(
            record=record,
            row=None,
            # RowRef будет рассчитан позже на этапах enrich/validate.
            row_ref=None,
            match_key=None,
        )

        def add_error(code: str, message: str | None = None, field: str | None = None):
            return result.add_error(
                stage=DiagnosticStage.MAP,
                code=code,
                field=field,
                message=message,
            )

        raw = record.values
        raw_id = _normalize(_read_source_value(raw, "raw_id", errors, add_error))
        full_name = _normalize(_read_source_value(raw, "full_name", errors, add_error))
        login = _normalize(_read_source_value(raw, "login", errors, add_error))
        email_or_phone = _normalize(_read_source_value(raw, "email_or_phone", errors, add_error))
        contacts = _normalize(_read_source_value(raw, "contacts", errors, add_error))
        manager = _normalize(_read_source_value(raw, "manager", errors, add_error))
        flags = _normalize(_read_source_value(raw, "flags", errors, add_error))
        employment = _normalize(_read_source_value(raw, "employment", errors, add_error))
        extra = _normalize(_read_source_value(raw, "extra", errors, add_error))

        last_name, first_name, middle_name = _split_full_name(full_name)
        email, phone = _pick_email_phone(email_or_phone, contacts)
        manager_id = _parse_manager_id(manager)
        disabled = _parse_disabled(flags)
        position = _parse_role(employment)
        extra_pairs = _parse_kv_pairs(extra)

        row = None
        secret_candidates = {}
        link_keys: dict[str, dict[str, str]] = {}
        if not errors:
            row = EmployeesRowPublic(
                email=email,
                last_name=last_name,
                first_name=first_name,
                middle_name=middle_name,
                is_logon_disable=disabled,
                user_name=login,
                phone=phone,
                password=extra_pairs.get("password"),
                personnel_number=raw_id,
                manager_id=manager_id,
                organization_id=extra_pairs.get("org_id"),
                position=position,
                avatar_id=None,
                usr_org_tab_num=extra_pairs.get("tab"),
                target_id=None,
            )
            secret_candidates = self.spec.collect_secret_candidates(row)
            if manager_id is not None and not isinstance(manager_id, int):
                match_key_value = normalize_whitespace(str(manager_id))
                if match_key_value:
                    link_keys["manager_id"] = {"match_key": match_key_value}

        result.row = row
        result.meta = {"link_keys": link_keys} if link_keys else {}
        result.secret_candidates = secret_candidates
        result.errors = errors
        result.warnings = warnings
        return result


_EMAIL_RE = re.compile(r"[^\s,;|]+@[^\s,;|]+")
_PHONE_RE = re.compile(r"[+\d][\d\s()\-]{5,}")
_MANAGER_ID_RE = re.compile(r"(?:manager_id|manager)\s*[:=]\s*([^;]+)", re.IGNORECASE)


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


def _read_source_value(
    raw: Mapping[str, str | None],
    field: str,
    errors: list[DiagnosticItem],
    add_error,
) -> str | None:
    """
    Назначение:
        Прочитать значение из SourceRecord по имени поля или по col_* схеме.
    """
    if field in raw:
        return raw.get(field)
    index = SOURCE_INDEX_SCHEMA.get(field)
    if index is not None:
        alt_key = f"col_{index}"
        if alt_key in raw:
            return raw.get(alt_key)
    errors.append(
        add_error(
            code="missing_source_column",
            field=field,
            message=f"Missing source column '{field}'",
        )
    )
    return None
