"""
Назначение:
    Чистая доменная политика проверки "пора ли выполнять ротацию ключей vault".

Граница ответственности:
    - Не выполняет IO и не зависит от delivery/infra.
    - Вычисляет due/not-due по timestamp последней успешной ротации и интервалу.
"""

from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass(frozen=True)
class VaultRotationInterval:
    """Интервал ротации (календарные months/years + фиксированные days/hours)."""

    hours: int = 0
    days: int = 0
    months: int = 0
    years: int = 0

    def __post_init__(self) -> None:
        if min(self.hours, self.days, self.months, self.years) < 0:
            raise ValueError("rotation interval values must be >= 0")
        if self.hours == 0 and self.days == 0 and self.months == 0 and self.years == 0:
            raise ValueError("rotation interval must contain at least one non-zero unit")


@dataclass(frozen=True)
class VaultRotationPolicy:
    """Политика вычисления due-состояния для ротации ключа vault."""

    interval: VaultRotationInterval

    def is_due(
        self,
        *,
        last_rotated_at: str | None,
        now_utc: str | datetime | None = None,
    ) -> bool:
        """Вернуть `True`, если по переданному времени ротацию уже нужно запускать."""
        if not last_rotated_at:
            return True

        now = _coerce_utc_datetime(now_utc) if now_utc is not None else datetime.now(timezone.utc)
        last_dt = _coerce_utc_datetime(last_rotated_at)
        if now < last_dt:
            return False
        due_at = _add_interval(last_dt, self.interval)
        return now >= due_at

    def next_due_at(self, *, last_rotated_at: str | datetime) -> datetime:
        """Рассчитать следующий due timestamp в UTC."""
        return _add_interval(_coerce_utc_datetime(last_rotated_at), self.interval)


def _coerce_utc_datetime(raw: str | datetime) -> datetime:
    if isinstance(raw, datetime):
        dt = raw
    else:
        normalized = raw.strip()
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _add_interval(base_utc: datetime, interval: VaultRotationInterval) -> datetime:
    shifted = _add_months(base_utc, interval.months + (interval.years * 12))
    return shifted + timedelta(days=interval.days, hours=interval.hours)


def _add_months(base_utc: datetime, months: int) -> datetime:
    if months == 0:
        return base_utc
    month_index = (base_utc.year * 12 + (base_utc.month - 1)) + months
    target_year = month_index // 12
    target_month = (month_index % 12) + 1
    target_day = min(base_utc.day, monthrange(target_year, target_month)[1])
    return base_utc.replace(year=target_year, month=target_month, day=target_day)


__all__ = ["VaultRotationInterval", "VaultRotationPolicy"]
