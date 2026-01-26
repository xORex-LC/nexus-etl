from __future__ import annotations

from connector.domain.models import ValidationErrorItem
from connector.domain.ports.sources import SourceMapper
from connector.domain.transform.result import TransformResult
from connector.domain.transform.source_record import SourceRecord
import re
from connector.datasets.employees.models import EmployeesRowPublic
from connector.datasets.employees.mapping_spec import EmployeesMappingSpec


class EmployeesSourceMapper(SourceMapper[EmployeesRowPublic]):
    """
    Назначение/ответственность:
        Маппинг CSV-строки сотрудников в публичную каноническую форму.
    """

    def __init__(self, spec: EmployeesMappingSpec | None = None) -> None:
        self.spec = spec or EmployeesMappingSpec()

    def map(self, record: SourceRecord) -> TransformResult[EmployeesRowPublic]:
        errors: list[ValidationErrorItem] = []
        warnings: list[ValidationErrorItem] = []

        raw = record.values
        raw_id = _normalize(raw.get("raw_id"))
        full_name = _normalize(raw.get("full_name"))
        login = _normalize(raw.get("login"))
        email_or_phone = _normalize(raw.get("email_or_phone"))
        contacts = _normalize(raw.get("contacts"))
        manager = _normalize(raw.get("manager"))
        flags = _normalize(raw.get("flags"))
        employment = _normalize(raw.get("employment"))
        extra = _normalize(raw.get("extra"))

        last_name, first_name, middle_name = _split_full_name(full_name)
        email, phone = _pick_email_phone(email_or_phone, contacts)
        manager_id = _parse_manager_id(manager)
        disabled = _parse_disabled(flags)
        position = _parse_role(employment)
        extra_pairs = _parse_kv_pairs(extra)

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
            resource_id=None,
        )

        secret_candidates = self.spec.collect_secret_candidates(row)

        return TransformResult(
            record=record,
            row=row,
            row_ref=None,
            match_key=None,
            secret_candidates=secret_candidates,
            errors=errors,
            warnings=warnings,
        )


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
