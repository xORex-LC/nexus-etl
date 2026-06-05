"""Run ledger observability backend — индекс запусков по компонентам.

Модуль хранит best-effort индекс запусков, который позволяет найти последний
run компонента и его артефакты без открытия report/plan/log файлов. Ledger
остаётся наблюдательным слоем: ошибки записи не должны ломать основной путь
команды.

Границы ответственности:
    - Сериализовать компактную запись запуска.
    - Поддерживать взаимозаменяемые backends `jsonl` и `sqlite`.
    - Давать prune-hook для retention sweeper.

Вне ответственности:
    - Решение, когда именно писать ledger-запись.
    - CLI-query/read side (`obs latest|tail`) — это следующий этап.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

from connector.common.observability import (
    LedgerBackendName,
    ObservabilityArtifactKind,
    ObservabilityLayout,
    ServiceComponent,
)
from connector.infra.sqlite.config import SqliteDbConfig
from connector.infra.sqlite.engine import open_sqlite


@dataclass(frozen=True)
class RunLedgerRowCounters:
    """Компактные агрегаты запуска для query-side без открытия отчёта."""

    rows_total: int = 0
    rows_passed: int = 0
    rows_blocked: int = 0
    rows_skipped: int = 0
    rows_with_warnings: int = 0
    errors_total: int = 0
    warnings_total: int = 0


@dataclass(frozen=True)
class RunLedgerRecord:
    """Одна append-only запись запуска компонента."""

    run_id: str
    pipeline_run_id: str
    component: str
    started_at: str
    finished_at: str | None
    status: str
    row_counters: RunLedgerRowCounters
    log_path: str | None
    report_path: str | None
    plan_path: str | None

    def to_payload(self) -> dict[str, Any]:
        """Сериализовать запись в JSON/SQLite-friendly payload."""
        payload = asdict(self)
        payload["row_counters"] = asdict(self.row_counters)
        return payload

    def artifact_path(self, artifact_kind: ObservabilityArtifactKind) -> str | None:
        """Вернуть путь нужного артефакта из ledger-записи."""
        if artifact_kind == ObservabilityArtifactKind.LOG:
            return self.log_path
        if artifact_kind == ObservabilityArtifactKind.REPORT:
            return self.report_path
        return self.plan_path


class RunLedgerBackend(Protocol):
    """Контракт append-only backend для индекса запусков."""

    backend_name: LedgerBackendName

    def append(
        self, *, component: ServiceComponent, record: RunLedgerRecord
    ) -> None: ...

    def prune(
        self,
        *,
        component: ServiceComponent,
        retention_days: int,
        now: datetime | None = None,
    ) -> tuple[Path, ...]: ...

    def latest_record(
        self,
        *,
        component: ServiceComponent,
    ) -> RunLedgerRecord | None: ...


class JsonlRunLedger:
    """Append-only ledger на JSON Lines в `var/logs/<component>/index.jsonl`."""

    backend_name: LedgerBackendName = "jsonl"

    def __init__(self, *, layout: ObservabilityLayout) -> None:
        self._layout = layout

    def append(self, *, component: ServiceComponent, record: RunLedgerRecord) -> None:
        ledger_path = self._layout.ledger_file(component, backend=self.backend_name)
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with ledger_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record.to_payload(), ensure_ascii=False))
            handle.write("\n")

    def prune(
        self,
        *,
        component: ServiceComponent,
        retention_days: int,
        now: datetime | None = None,
    ) -> tuple[Path, ...]:
        ledger_path = self._layout.ledger_file(component, backend=self.backend_name)
        if not ledger_path.exists() or not ledger_path.is_file():
            return ()
        resolved_now = now or datetime.now(timezone.utc)
        cutoff = resolved_now.astimezone(timezone.utc).date() - timedelta(
            days=retention_days
        )

        kept_lines: list[str] = []
        for line in ledger_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            if self._should_keep_jsonl_line(line=line, cutoff=cutoff):
                kept_lines.append(line)

        payload = "\n".join(kept_lines)
        temp_payload = payload + ("\n" if kept_lines else "")
        temp_path = ledger_path.with_suffix(f"{ledger_path.suffix}.tmp")
        temp_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path.write_text(temp_payload, encoding="utf-8")
        temp_path.replace(ledger_path)
        return (ledger_path,)

    def latest_record(
        self,
        *,
        component: ServiceComponent,
    ) -> RunLedgerRecord | None:
        ledger_path = self._layout.ledger_file(component, backend=self.backend_name)
        if not ledger_path.exists() or not ledger_path.is_file():
            return None

        for line in reversed(ledger_path.read_text(encoding="utf-8").splitlines()):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            record = _record_from_payload(payload)
            if record is not None:
                return record
        return None

    @staticmethod
    def _should_keep_jsonl_line(*, line: str, cutoff: date) -> bool:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            return True
        effective_iso = payload.get("finished_at") or payload.get("started_at")
        if not isinstance(effective_iso, str):
            return True
        try:
            effective_dt = datetime.fromisoformat(effective_iso)
        except ValueError:
            return True
        return effective_dt.astimezone(timezone.utc).date() >= cutoff


class SqliteRunLedger:
    """Ledger backend на SQLite в `var/logs/<component>/index.sqlite3`."""

    backend_name: LedgerBackendName = "sqlite"

    def __init__(
        self,
        *,
        layout: ObservabilityLayout,
        sqlite_config: SqliteDbConfig,
    ) -> None:
        self._layout = layout
        self._sqlite_config = sqlite_config

    def append(self, *, component: ServiceComponent, record: RunLedgerRecord) -> None:
        ledger_path = self._layout.ledger_file(component, backend=self.backend_name)
        engine = open_sqlite(self._sqlite_config, str(ledger_path))
        try:
            self._ensure_schema(engine)
            with engine.transaction():
                engine.execute(
                    """
                    INSERT INTO run_ledger (
                        run_id,
                        pipeline_run_id,
                        component,
                        started_at,
                        finished_at,
                        status,
                        rows_total,
                        rows_passed,
                        rows_blocked,
                        rows_skipped,
                        rows_with_warnings,
                        errors_total,
                        warnings_total,
                        log_path,
                        report_path,
                        plan_path
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.run_id,
                        record.pipeline_run_id,
                        record.component,
                        record.started_at,
                        record.finished_at,
                        record.status,
                        record.row_counters.rows_total,
                        record.row_counters.rows_passed,
                        record.row_counters.rows_blocked,
                        record.row_counters.rows_skipped,
                        record.row_counters.rows_with_warnings,
                        record.row_counters.errors_total,
                        record.row_counters.warnings_total,
                        record.log_path,
                        record.report_path,
                        record.plan_path,
                    ),
                )
        finally:
            engine.close()

    def prune(
        self,
        *,
        component: ServiceComponent,
        retention_days: int,
        now: datetime | None = None,
    ) -> tuple[Path, ...]:
        ledger_path = self._layout.ledger_file(component, backend=self.backend_name)
        if not ledger_path.exists() or not ledger_path.is_file():
            return ()
        resolved_now = now or datetime.now(timezone.utc)
        cutoff = (
            resolved_now.astimezone(timezone.utc) - timedelta(days=retention_days)
        ).isoformat()
        engine = open_sqlite(self._sqlite_config, str(ledger_path))
        try:
            self._ensure_schema(engine)
            with engine.transaction():
                engine.execute(
                    """
                    DELETE FROM run_ledger
                    WHERE COALESCE(finished_at, started_at) < ?
                    """,
                    (cutoff,),
                )
            engine.execute("VACUUM")
        finally:
            engine.close()
        return (ledger_path,)

    def latest_record(
        self,
        *,
        component: ServiceComponent,
    ) -> RunLedgerRecord | None:
        ledger_path = self._layout.ledger_file(component, backend=self.backend_name)
        if not ledger_path.exists() or not ledger_path.is_file():
            return None
        engine = open_sqlite(self._sqlite_config, str(ledger_path))
        try:
            self._ensure_schema(engine)
            row = engine.fetchone(
                """
                SELECT
                    run_id,
                    pipeline_run_id,
                    component,
                    started_at,
                    finished_at,
                    status,
                    rows_total,
                    rows_passed,
                    rows_blocked,
                    rows_skipped,
                    rows_with_warnings,
                    errors_total,
                    warnings_total,
                    log_path,
                    report_path,
                    plan_path
                FROM run_ledger
                WHERE component = ?
                ORDER BY COALESCE(finished_at, started_at) DESC, id DESC
                LIMIT 1
                """,
                (component.value,),
            )
            return _record_from_sqlite_row(row)
        finally:
            engine.close()

    @staticmethod
    def _ensure_schema(engine) -> None:
        engine.execute(
            """
            CREATE TABLE IF NOT EXISTS run_ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                pipeline_run_id TEXT NOT NULL,
                component TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL,
                rows_total INTEGER NOT NULL,
                rows_passed INTEGER NOT NULL,
                rows_blocked INTEGER NOT NULL,
                rows_skipped INTEGER NOT NULL,
                rows_with_warnings INTEGER NOT NULL,
                errors_total INTEGER NOT NULL,
                warnings_total INTEGER NOT NULL,
                log_path TEXT,
                report_path TEXT,
                plan_path TEXT
            )
            """
        )
        engine.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_run_ledger_component_finished
            ON run_ledger(component, finished_at, started_at)
            """
        )


def build_run_ledger_backend(
    *,
    backend: LedgerBackendName,
    layout: ObservabilityLayout,
    sqlite_config: SqliteDbConfig,
) -> RunLedgerBackend:
    """Построить ledger backend согласно observability config."""
    if backend == "sqlite":
        return SqliteRunLedger(layout=layout, sqlite_config=sqlite_config)
    return JsonlRunLedger(layout=layout)


def build_run_ledger_record(
    *,
    run_id: str,
    pipeline_run_id: str,
    component: ServiceComponent,
    started_at: str,
    finished_at: str | None,
    status: str,
    log_path: str | None,
    report_path: str | None,
    plan_path: str | None,
    row_counters: RunLedgerRowCounters | None = None,
) -> RunLedgerRecord:
    """Собрать typed ledger record на границе runtime orchestration."""
    return RunLedgerRecord(
        run_id=run_id,
        pipeline_run_id=pipeline_run_id,
        component=component.value,
        started_at=started_at,
        finished_at=finished_at,
        status=status,
        row_counters=row_counters or RunLedgerRowCounters(),
        log_path=log_path,
        report_path=report_path,
        plan_path=plan_path,
    )


def _record_from_payload(payload: object) -> RunLedgerRecord | None:
    if not isinstance(payload, dict):
        return None
    row_counters_payload = payload.get("row_counters")
    row_counters_dict = (
        row_counters_payload if isinstance(row_counters_payload, dict) else {}
    )
    return RunLedgerRecord(
        run_id=str(payload.get("run_id", "")),
        pipeline_run_id=str(payload.get("pipeline_run_id", "")),
        component=str(payload.get("component", "")),
        started_at=str(payload.get("started_at", "")),
        finished_at=(
            str(payload["finished_at"])
            if isinstance(payload.get("finished_at"), str)
            else None
        ),
        status=str(payload.get("status", "")),
        row_counters=RunLedgerRowCounters(
            rows_total=int(row_counters_dict.get("rows_total", 0)),
            rows_passed=int(row_counters_dict.get("rows_passed", 0)),
            rows_blocked=int(row_counters_dict.get("rows_blocked", 0)),
            rows_skipped=int(row_counters_dict.get("rows_skipped", 0)),
            rows_with_warnings=int(row_counters_dict.get("rows_with_warnings", 0)),
            errors_total=int(row_counters_dict.get("errors_total", 0)),
            warnings_total=int(row_counters_dict.get("warnings_total", 0)),
        ),
        log_path=payload.get("log_path")
        if isinstance(payload.get("log_path"), str)
        else None,
        report_path=payload.get("report_path")
        if isinstance(payload.get("report_path"), str)
        else None,
        plan_path=payload.get("plan_path")
        if isinstance(payload.get("plan_path"), str)
        else None,
    )


def _record_from_sqlite_row(row: Any) -> RunLedgerRecord | None:
    if row is None:
        return None
    return RunLedgerRecord(
        run_id=str(row["run_id"]),
        pipeline_run_id=str(row["pipeline_run_id"]),
        component=str(row["component"]),
        started_at=str(row["started_at"]),
        finished_at=str(row["finished_at"]) if row["finished_at"] is not None else None,
        status=str(row["status"]),
        row_counters=RunLedgerRowCounters(
            rows_total=int(row["rows_total"]),
            rows_passed=int(row["rows_passed"]),
            rows_blocked=int(row["rows_blocked"]),
            rows_skipped=int(row["rows_skipped"]),
            rows_with_warnings=int(row["rows_with_warnings"]),
            errors_total=int(row["errors_total"]),
            warnings_total=int(row["warnings_total"]),
        ),
        log_path=str(row["log_path"]) if row["log_path"] is not None else None,
        report_path=(
            str(row["report_path"]) if row["report_path"] is not None else None
        ),
        plan_path=str(row["plan_path"]) if row["plan_path"] is not None else None,
    )


__all__ = [
    "JsonlRunLedger",
    "RunLedgerBackend",
    "RunLedgerRecord",
    "RunLedgerRowCounters",
    "SqliteRunLedger",
    "build_run_ledger_backend",
    "build_run_ledger_record",
]
