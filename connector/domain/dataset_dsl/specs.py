"""
Назначение:
    Pydantic-модели для dataset-level DSL конфигурации.

Граница ответственности:
    - Owns: декларативные модели report/apply/diagnostics секций runtime registry file.
    - Does NOT: загрузка YAML, компиляция в runtime-объекты.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from connector.domain.dsl.specs._base import DslBaseModel


class ReportAdapterSpec(DslBaseModel):
    """
    Назначение:
        Конфигурация report adapter для датасета.
    """

    identity_label: str
    conflict_code: str
    conflict_field: str


class PayloadSpec(DslBaseModel):
    """
    Назначение:
        Конфигурация payload building для apply adapter.

    Поля:
        source: откуда берутся field mappings ("sink" = из SinkSpec).
        defaults: constant fields, инжектируемые в payload.
        conditional_fields: поля, включаемые только когда non-empty.
    """

    source: Literal["sink"] = "sink"
    defaults: dict[str, Any] = Field(default_factory=dict)
    conditional_fields: list[str] = Field(default_factory=list)


class ParamsSpec(DslBaseModel):
    """
    Назначение:
        Конфигурация operation params builder.

    Режимы:
        target_id: извлечение и валидация target_id из PlanItem.
        none: params не используются.
    """

    mode: Literal["target_id", "none"] = "target_id"


class ApplyAdapterSpec(DslBaseModel):
    """
    Назначение:
        Конфигурация apply adapter для датасета.
    """

    operation_alias: str
    payload: PayloadSpec = Field(default_factory=PayloadSpec)
    params: ParamsSpec = Field(default_factory=ParamsSpec)


class DiagnosticEntrySpec(DslBaseModel):
    """
    Назначение:
        Декларативное описание диагностического кода.
    """

    code: str
    system_code: str
    severity: str
    message: str = ""


class DatasetDslSpec(DslBaseModel):
    """
    Назначение:
        Полная dataset-level DSL конфигурация из runtime registry file.
    """

    report: ReportAdapterSpec
    apply: ApplyAdapterSpec
    diagnostics: list[DiagnosticEntrySpec] = Field(default_factory=list)
