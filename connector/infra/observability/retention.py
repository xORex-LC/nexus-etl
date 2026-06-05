"""Observability retention — безопасная чистка устаревших лог-артефактов

Модуль реализует sweeper для observability-файлов. Он работает только внутри
каталога компонента, не следует по симлинкам и троттлит sweep не чаще одного
раза в день через marker-файл.

Границы ответственности:
    - Удалять файлы старше заданного retention_days.
    - Ограничивать число size-roll backup-файлов внутри одного дня.
    - Соблюдать guardrails по симлинкам и допустимым паттернам имён.

Вне ответственности:
    - Вызов sweeper из CLI orchestration.
    - Удаление произвольных файлов вне observability naming pattern.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from connector.common.observability import ObservabilityLayout, ServiceComponent
from connector.infra.observability.ledger import RunLedgerBackend

_STAMP_PATTERN = re.compile(
    r"^(?P<stamp>\d{4}-\d{2}-\d{2}(?:T\d{2}-\d{2}-\d{2})?)_(?P<component>[a-z0-9_-]+)(?:\.(?P<roll>\d+))?\.(?P<ext>[a-z0-9]+)$"
)


@dataclass(frozen=True)
class RetentionSweepResult:
    """Итог одного sweep-запуска для вызывающего кода и тестов."""

    deleted_files: tuple[Path, ...]
    skipped_by_marker: bool


class ObservabilityRetentionSweeper:
    """Чистить observability-файлы по age и backup limit в пределах компонента."""

    def __init__(
        self,
        *,
        layout: ObservabilityLayout,
        ledger_backend: RunLedgerBackend | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._layout = layout
        self._ledger_backend = ledger_backend
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def sweep_logs(
        self,
        *,
        component: ServiceComponent,
        retention_days: int,
        retention_backups: int,
        now: datetime | None = None,
    ) -> RetentionSweepResult:
        """Выполнить safe sweep для log-root выбранного компонента."""
        resolved_now = now or self._clock()
        return self._sweep_root(
            root_dir=self._layout.log_file(component, now=resolved_now).parent,
            component=component,
            retention_days=retention_days,
            retention_backups=retention_backups,
            now=resolved_now,
            marker_name=".retention.marker",
        )

    def sweep_reports(
        self,
        *,
        component: ServiceComponent,
        retention_days: int,
        now: datetime | None = None,
    ) -> RetentionSweepResult:
        """Выполнить safe sweep для report-root выбранного компонента."""
        resolved_now = now or self._clock()
        return self._sweep_root(
            root_dir=self._layout.report_file(component, now=resolved_now).parent,
            component=component,
            retention_days=retention_days,
            retention_backups=0,
            now=resolved_now,
            marker_name=".report-retention.marker",
        )

    def sweep_plans(
        self,
        *,
        component: ServiceComponent,
        retention_days: int,
        now: datetime | None = None,
    ) -> RetentionSweepResult:
        """Выполнить safe sweep для plan-root выбранного компонента."""
        resolved_now = now or self._clock()
        return self._sweep_root(
            root_dir=self._layout.plan_file(component, now=resolved_now).parent,
            component=component,
            retention_days=retention_days,
            retention_backups=0,
            now=resolved_now,
            marker_name=".plan-retention.marker",
        )

    def sweep_ledger(
        self,
        *,
        component: ServiceComponent,
        retention_days: int,
        now: datetime | None = None,
    ) -> RetentionSweepResult:
        """Выполнить best-effort retention для run ledger компонента."""
        if self._ledger_backend is None:
            return RetentionSweepResult(deleted_files=(), skipped_by_marker=True)

        resolved_now = now or self._clock()
        root_dir = self._layout.log_file(component, now=resolved_now).parent
        marker_path = root_dir / ".ledger-retention.marker"
        marker_day = resolved_now.astimezone(timezone.utc).date().isoformat()
        if marker_path.exists() and marker_path.is_file():
            marker_value = marker_path.read_text(encoding="utf-8").strip()
            if marker_value == marker_day:
                return RetentionSweepResult(deleted_files=(), skipped_by_marker=True)

        root_dir.mkdir(parents=True, exist_ok=True)
        touched_files = self._ledger_backend.prune(
            component=component,
            retention_days=retention_days,
            now=resolved_now,
        )
        marker_path.write_text(marker_day, encoding="utf-8")
        return RetentionSweepResult(
            deleted_files=tuple(sorted(touched_files)),
            skipped_by_marker=False,
        )

    def _sweep_root(
        self,
        *,
        root_dir: Path,
        component: ServiceComponent,
        retention_days: int,
        retention_backups: int,
        now: datetime,
        marker_name: str,
    ) -> RetentionSweepResult:
        marker_path = root_dir / marker_name
        marker_day = now.astimezone(timezone.utc).date().isoformat()

        if marker_path.exists() and marker_path.is_file():
            marker_value = marker_path.read_text(encoding="utf-8").strip()
            if marker_value == marker_day:
                return RetentionSweepResult(deleted_files=(), skipped_by_marker=True)

        deleted: list[Path] = []
        if root_dir.exists():
            deleted.extend(
                self._delete_expired_files(
                    component_dir=root_dir,
                    component=component,
                    retention_days=retention_days,
                    retention_backups=retention_backups,
                    today=now.astimezone(timezone.utc).date(),
                )
            )

        root_dir.mkdir(parents=True, exist_ok=True)
        marker_path.write_text(marker_day, encoding="utf-8")
        return RetentionSweepResult(
            deleted_files=tuple(sorted(deleted)), skipped_by_marker=False
        )

    def _delete_expired_files(
        self,
        *,
        component_dir: Path,
        component: ServiceComponent,
        retention_days: int,
        retention_backups: int,
        today: date,
    ) -> list[Path]:
        candidates_by_stamp: dict[str, list[tuple[Path, int | None]]] = {}
        deleted: list[Path] = []
        cutoff = today - timedelta(days=retention_days)

        for entry in component_dir.iterdir():
            if entry.is_symlink() or not entry.is_file():
                continue
            match = _STAMP_PATTERN.match(entry.name)
            if match is None or match.group("component") != component.value:
                continue
            stamp = match.group("stamp")
            stamp_day = self._stamp_to_date(stamp)
            if stamp_day < cutoff:
                entry.unlink()
                deleted.append(entry)
                continue
            roll = match.group("roll")
            candidates_by_stamp.setdefault(stamp, []).append(
                (entry, int(roll) if roll is not None else None)
            )

        for stamp_entries in candidates_by_stamp.values():
            backups = sorted(
                ((path, roll) for path, roll in stamp_entries if roll is not None),
                key=lambda item: item[1],
            )
            for path, _roll in backups[retention_backups:]:
                path.unlink()
                deleted.append(path)

        return deleted

    def _stamp_to_date(self, stamp: str) -> date:
        if "T" in stamp:
            return datetime.strptime(stamp, "%Y-%m-%dT%H-%M-%S").date()
        return datetime.strptime(stamp, "%Y-%m-%d").date()
