from __future__ import annotations

from dataclasses import dataclass
from typing import Any

class EntityType:
    """
    Константы типов сущностей в планах.
    """

    EMPLOYEE = "employee"


class Operation:
    """
    Константы операций плана.
    """

    CREATE = "create"
    UPDATE = "update"

@dataclass
class PlanMeta:
    """
    Назначение:
        Метаданные плана: источник, время генерации, настройки.
    """

    run_id: str | None
    generated_at: str | None
    dataset: str | None
    csv_path: str | None
    plan_path: str | None
    include_deleted_users: bool | None

@dataclass
class PlanSummary:
    """
    Назначение:
        Агрегированные счётчики по плану.

    Поля:
        rows_total: всего строк в источнике
        valid_rows: строк, прошедших валидацию
        failed_rows: строк, отфильтрованных валидатором/планировщиком
        planned_create/planned_update: количество операций
        skipped: валидные строки без изменений (не попадают в items)
    """

    rows_total: int
    valid_rows: int
    failed_rows: int
    planned_create: int
    planned_update: int
    skipped: int

@dataclass
class PlanItem:
    """
    Назначение:
        Операция плана для последующего применения.

    Поля:
        entity_type: тип сущности (например, employee)
        op: операция (create/update)
        resource_id: идентификатор ресурса (новый UUID для create, существующий id для update)
        desired_state: полное желаемое состояние (для create; для update можно хранить тоже полное)
        changes: частичный словарь изменённых полей (для update)
        row_id/line_no/source_ref: ссылки на исходные данные для трассировки
    """

    row_id: str
    line_no: int | None
    entity_type: str
    op: str
    resource_id: str
    desired_state: dict[str, Any]
    changes: dict[str, Any]
    source_ref: dict[str, Any] | None = None

@dataclass
class Plan:
    """
    Назначение:
        Корневой объект плана.
    """

    meta: PlanMeta
    summary: PlanSummary
    items: list[PlanItem]
