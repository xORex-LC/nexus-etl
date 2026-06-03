"""Controlled, in-memory dataset specs for tests — decoupled from datasets/ YAML.

Назначение:
    Дать тестам пайплайн-движки поверх ФИКСИРОВАННЫХ, принадлежащих тесту спек,
    чтобы правка реального (gitignored) employees YAML не ломала тесты механики.
    Ассерты мигрированных тестов сверяются с контролируемыми спеками здесь, а не
    с содержимым на диске.

Зона ответственности:
    - Хранить минимальный контролируемый датасет (copy / split_name / multi-source
      list aggregation), воспроизводящий механику, на которую опирались employees-тесты
    - Собирать движки (mapper и далее) из этих спек без `from_dataset(...)`

Вне области ответственности:
    - Запись temp-датасета на диск для CLI/e2e (добавим по мере миграции таких тестов)
    - Воспроизведение точного содержимого реального employees-датасета

Расширять инкрементально по мере перевода новых тестов с `from_dataset(...)`.
"""

from __future__ import annotations

from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.diagnostics.core_catalog import build_core_catalog
from connector.domain.transform.mapping import MapperEngine
from connector.domain.transform.normalize import NormalizerEngine
from connector.domain.transform.core.source_record import SourceRecord
from connector.domain.transform_dsl.build_options import MapDslBuildOptions
from connector.domain.transform_dsl.specs import MappingSpec, NormalizeSpec, SinkSpec

# Контролируемый датасет "people": фиксированные имена колонок и правил.
CONTROLLED_DATASET = "controlled_people"

CONTROLLED_SOURCE_COLUMNS = [
    "emp_id",
    "last_raw",
    "first_raw",
    "unit_l1",
    "unit_l2",
    "unit_l3",
    "phone_raw",
    "active_flag",
]


def controlled_catalog() -> ErrorCatalog:
    """Каталог диагностик для контролируемого датасета."""
    return build_core_catalog(strict=False)


def controlled_mapping_spec() -> MappingSpec:
    """Маппинг, воспроизводящий ключевую механику employees: copy и multi-source list."""
    return MappingSpec.model_validate(
        {
            "dataset": CONTROLLED_DATASET,
            "source_columns": CONTROLLED_SOURCE_COLUMNS,
            "mapping": {
                "rules": [
                    {"target": "code", "source": "emp_id", "ops": [{"op": "trim"}]},
                    {"target": "last_name", "source": "last_raw", "ops": [{"op": "trim"}]},
                    {"target": "first_name", "source": "first_raw", "ops": [{"op": "trim"}]},
                    {
                        "target": "org_path",
                        "sources": ["unit_l1", "unit_l2", "unit_l3"],
                        "op": "copy",
                    },
                    {"target": "phone", "source": "phone_raw", "ops": [{"op": "trim"}]},
                    {"target": "is_active", "source": "active_flag", "ops": [{"op": "trim"}]},
                ]
            },
        }
    )


def controlled_sink_spec(*, org_path_type: str = "list") -> SinkSpec:
    """Sink, согласованный с targets контролируемого маппинга.

    `org_path_type` параметризован: `list` — для mapper (multi-source агрегация),
    `string` — для normalizer (после `compact`+`last` это уже скаляр).
    """
    return SinkSpec.model_validate(
        {
            "dataset": CONTROLLED_DATASET,
            "sink": {
                "fields": [
                    {"name": "code", "type": "string"},
                    {"name": "last_name", "type": "string"},
                    {"name": "first_name", "type": "string"},
                    {"name": "org_path", "type": org_path_type},
                    {"name": "phone", "type": "string"},
                    {"name": "is_active", "type": "string"},
                ]
            },
        }
    )


def build_mapper(*, catalog: ErrorCatalog | None = None) -> MapperEngine:
    """Собрать MapperEngine поверх контролируемых mapping/sink спек."""
    return MapperEngine(
        controlled_mapping_spec(),
        catalog=catalog or controlled_catalog(),
        sink_spec=controlled_sink_spec(),
        options=MapDslBuildOptions(),
    )


def controlled_normalize_spec() -> NormalizeSpec:
    """Normalize: из multi-source списка `org_path` берём последнее непустое значение."""
    return NormalizeSpec.model_validate(
        {
            "dataset": CONTROLLED_DATASET,
            "normalize": {
                "rules": [
                    {"field": "org_path", "ops": [{"op": "compact"}, {"op": "last"}]},
                ]
            },
        }
    )


def build_normalizer(*, catalog: ErrorCatalog | None = None) -> NormalizerEngine:
    """Собрать NormalizerEngine поверх контролируемых normalize/sink спек."""
    return NormalizerEngine(
        controlled_normalize_spec(),
        catalog=catalog or controlled_catalog(),
        sink_spec=controlled_sink_spec(org_path_type="string"),
    )


def controlled_source_record(**values: object) -> SourceRecord:
    """SourceRecord с контролируемыми колонками; недостающие — пустые строки."""
    row = {column: "" for column in CONTROLLED_SOURCE_COLUMNS}
    row.update({key: str(value) for key, value in values.items()})
    return SourceRecord(line_no=1, record_id="line:1", values=row)
