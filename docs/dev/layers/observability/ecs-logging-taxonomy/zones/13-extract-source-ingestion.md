# Zone 13: Extract / Source Ingestion

Тринадцатая зона описывает input boundary перед transform pipeline: загрузку source DSL, resolution
физического источника, открытие CSV-файла, чтение строк и перевод `SourceRecord` в поток
`TransformResult[None]`.

В текущей архитектуре Extract — это не обычная `StageContract` стадия внутри `PipelineOrchestrator`.
Он состоит из двух слоёв:

- `CsvRecordSource` в `connector/infra/sources/csv_reader.py` — file I/O, CSV parsing, null
  normalization, structural CSV failures;
- `Extractor` в `connector/domain/transform/core/extractor.py` — stream boundary, wrapping
  `SourceRecord` в `TransformResult`, conversion source exceptions → `SOURCE_ERROR`.

Эта зона отвечает на вопрос: **какой источник был выбран, с какими физическими параметрами он
читался, сколько строк реально вошло в pipeline и где именно сломался source boundary**.

### Границы зоны

- `stage-started` / `stage-completed` из Zone 3 не описывают Extract, пока Extract не является
  `StageContract` stage с `nexus.stage.name`.
- `dsl-spec-loaded`, `dsl-validation-failed`, `SOURCE_DSL_*` остаются в Zone 7; эта зона использует
  уже загруженный `SourceSpec` и описывает runtime ingestion.
- Mapping/Normalize не должны логировать физические CSV details. Они получают уже `SourceRecord`.
- Topology adjacency readers (`PolarsSourceAdjacencyReader`) относятся к будущей topology zone, не к
  обычному Extract path.
- Raw `SourceRecord.values`, CSV row values, header values как список, PII и full row payload не
  логируются.

### Реальная модель, на которую опираемся

| Code model | Logging meaning |
|---|---|
| `load_source_spec_for_dataset()` | source DSL is available; detailed DSL failures belong to Zone 7 |
| `resolve_source_location()` | `source-resolved`, logical source location → runtime path |
| `YamlDatasetSpec.build_record_source()` | source adapter constructed from preloaded `SourceSpec` |
| `CsvRecordSource.__iter__()` | `source-read-started`, `source-header-read`, `source-record-read`, `source-read-completed`, `source-read-failed` |
| `CsvFormatError` | structural source failure; map to `source-read-failed` with `error.code=SOURCE_ERROR` or future CSV-specific code |
| `Extractor.run()` | `source-stream-wrapped`, `source-stream-failed`; converts source exception to `DiagnosticStage.EXTRACT` / `SOURCE_ERROR` |
| `SourceRecord(line_no, record_id, values)` | `nexus.record.*`, field/null counters only; raw values are forbidden |

### Canonical taxonomy для source lifecycle

| Action | Bucket | Default level | Outcome | Required ECS fields | Typical project fields | Emission point |
|---|---|---|---|---|---|---|
| `source-resolved` | INFO decision | `info` | `success` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `service.type` | `nexus.subsystem=source`, `nexus.source.type`, `nexus.source.format`, `nexus.source.location`, `nexus.source.path_kind`, `file.path` | after `resolve_source_location()` succeeds |
| `source-resolution-failed` | INFO milestone | `error` | `failure` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `service.type`, `error.code`, `error.message` | `nexus.subsystem=source`, `nexus.source.type`, `nexus.source.format`, `nexus.source.location`, `nexus.source.reason` | source spec/location cannot resolve to runtime input |
| `source-read-started` | INFO milestone | `info` | — | `event.action`, `trace.id`, `event.dataset`, `service.type` | `nexus.subsystem=source`, `nexus.source.type=file`, `nexus.source.format=csv`, `file.path`, `file.size`, `nexus.source.encoding`, `nexus.source.delimiter`, `nexus.source.has_header` | before opening/iterating CSV source |
| `source-header-read` | DEBUG decision | `debug`/`warning` | `success`/`failure` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `service.type` | `nexus.subsystem=source`, `nexus.source.header.present`, `nexus.source.columns.count`, `nexus.source.columns.fingerprint`, `nexus.source.declared_fields_count`, `nexus.source.missing_columns_count`, `nexus.source.extra_columns_count` | after CSV header or synthetic no-header columns are known |
| `source-contract-evaluated` | INFO/DEBUG decision | `info`/`warning` | `success`/`failure`/`unknown` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `service.type` | `nexus.subsystem=source`, `nexus.source.declared_fields_count`, `nexus.source.columns.count`, `nexus.source.missing_columns_count`, `nexus.source.extra_columns_count`, `nexus.source.reason` | optional check between `SourceSpec.fields` and observed header/columns |
| `source-read-completed` | INFO milestone | `info` | `success` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `service.type`, `event.duration` | `nexus.subsystem=source`, `nexus.source.records_total`, `nexus.source.blank_rows_skipped`, `nexus.source.rows_with_nulls`, `nexus.source.null_values_total`, `nexus.source.columns.count`, `file.size` | after source iterator is exhausted successfully |
| `source-read-failed` | INFO milestone | `error` | `failure` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `service.type`, `error.type`, `error.message` | `nexus.subsystem=source`, `nexus.source.reason`, `nexus.source.failure.line_no`, `nexus.source.failure.expected_columns`, `nexus.source.failure.actual_columns`, `nexus.source.records_total`, `file.path` | source open/read/parse failed before stream completed |
| `source-stream-wrapped` | DEBUG decision | `debug` | `success` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `service.type` | `nexus.subsystem=source`, `nexus.record.id`, `nexus.record.line_no`, `nexus.source.record.fields_count`, `nexus.source.record.null_fields_count` | `Extractor` wraps one `SourceRecord` into `TransformResult` |
| `source-stream-failed` | INFO milestone | `error` | `failure` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `service.type`, `error.code`, `error.message` | `nexus.subsystem=source`, `nexus.source.reason`, `nexus.record.id=source`, `nexus.stage.name=extract`, `nexus.diagnostic.code=SOURCE_ERROR` | `Extractor.run()` catches source exception and yields diagnostic result |

### Optional forensic events

| Action | Bucket | Default level | Outcome | Required ECS fields | Typical project fields | Emission point |
|---|---|---|---|---|---|---|
| `source-record-read` | TRACE diagnostic | `trace` | `success` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `service.type`, `nexus.record.id` | `nexus.record.line_no`, `nexus.source.record.fields_count`, `nexus.source.record.null_fields_count`, `nexus.source.record.empty_fields_count` | sampled per-record read event, disabled by default |
| `source-blank-row-skipped` | TRACE diagnostic | `trace` | `success` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `service.type` | `nexus.source.failure.line_no` or `nexus.record.line_no`, `nexus.source.reason=blank_row` | optional per blank row skip; baseline should aggregate count |

### Нормализация и анти-дублирование

- `source-read-started` / `source-read-completed` — lifecycle физического input stream. Они не
  заменяют `stage-started` / `stage-completed`, пока Extract не встроен как обычная stage.
- `source-resolved` не должен дублировать `dsl-spec-loaded`: resolution — runtime path decision, DSL
  loading — artifact lifecycle.
- `source-header-read` и `source-contract-evaluated` разделены: header — что реально увидели в файле,
  contract — как это соотносится с `SourceSpec.fields`.
- Baseline logs не должны эмитить `source-record-read` на каждую строку. Для ES-мониторинга обычно
  достаточно aggregate counters на `source-read-completed` и precise failure line on error.
- `source-read-failed` и `source-stream-failed` могут появиться для одного сбоя на разных слоях.
  Если при внедрении появится единый telemetry sink, предпочтительно оставить один error milestone и
  добавить `nexus.source.failure.layer=reader|extractor`.

### Минимальный field profile

| Поле | Статус | Примечание |
|---|---|---|
| `event.action` | required | из source ingestion action dictionary |
| `event.outcome` | required on completion/failure | `success` / `failure` / `unknown` |
| `trace.id` | required | command/pipeline run correlation |
| `event.dataset` | required | source всегда dataset-aware в текущем pipeline |
| `service.type` | required | component identity текущей команды (`mapper`, `normalizer`, `planner`, ...) |
| `nexus.subsystem` | required | `source` |
| `nexus.stage.name` | optional | использовать `extract` только для bridge/diagnostic events, пока Extract не `StageContract` |
| `file.path` | recommended | безопасный runtime path; по возможности relative/logical, не dense per-record |
| `file.name`, `file.size` | recommended | useful for file identity without row payload |
| `nexus.source.location` | recommended | logical `source.location` from `SourceSpec` |
| `nexus.source.path_kind` | recommended | `relative`, `absolute`, `logical`, `unknown` |
| `nexus.source.type` | required | current supported runtime path: `file` |
| `nexus.source.format` | required | current supported runtime path: `csv` |
| `nexus.source.encoding` | required for CSV | e.g. `utf-8-sig` |
| `nexus.source.delimiter` | required for CSV | single-character delimiter, escaped if needed |
| `nexus.source.has_header` | required for CSV | boolean from `SourceSpec` |
| `nexus.source.header.present` | recommended | observed header presence/result |
| `nexus.source.columns.count` | recommended | observed physical/synthetic column count |
| `nexus.source.columns.fingerprint` | recommended | safe hash of ordered column names; no raw header list |
| `nexus.source.declared_fields_count` | recommended | number of `SourceSpec.fields` |
| `nexus.source.missing_columns_count`, `nexus.source.extra_columns_count` | recommended for contract evaluation | counts only; raw names optional and normally not emitted |
| `nexus.source.records_total` | required on completion/failure when known | records yielded before completion/failure |
| `nexus.source.blank_rows_skipped` | recommended | aggregate skipped blank rows |
| `nexus.source.rows_with_nulls` | recommended | count rows where `parse_null()` produced at least one null |
| `nexus.source.null_values_total` | recommended | aggregate null-normalized values |
| `nexus.source.record.fields_count` | optional per-record | count of fields in one `SourceRecord.values` |
| `nexus.source.record.null_fields_count` | optional per-record | count of nulls in one record; no values |
| `nexus.source.failure.line_no` | required on structural row failures when known | CSV line where parsing failed |
| `nexus.source.failure.expected_columns`, `nexus.source.failure.actual_columns` | recommended on column mismatch | counts from `CsvFormatError` context if parsed |
| `nexus.source.failure.layer` | recommended on failures | `dsl`, `resolver`, `reader`, `extractor` |
| `nexus.source.reason` | recommended on failure/degraded events | `file_not_found`, `missing_header`, `column_count_mismatch`, `decode_error`, ... |
| `nexus.diagnostic.code` | recommended on `source-stream-failed` | current diagnostic code: `SOURCE_ERROR` |
| `error.type`, `error.message`, `error.code` | required on failures | `error.code=SOURCE_ERROR` until CSV-specific catalog codes exist |

### Detail policy для Extract / Source Ingestion

- `INFO` — source resolved/read started/read completed, source contract evaluated when it can affect
  operator confidence, source failure.
- `DEBUG` — header profile, extractor wrapping summary, non-fatal source contract details.
- `WARNING` — contract mismatch that the current runtime can continue through, suspicious empty source,
  unexpected but recoverable source conditions.
- `ERROR` — file open/read/decode/CSV structural failure, extractor-level `SOURCE_ERROR`.
- `TRACE` — sampled per-record events only; disabled by default because source streams can be large.

### Что не логировать

- Raw CSV row values and `SourceRecord.values`.
- Full header list by default; use `nexus.source.columns.fingerprint` and counts.
- PII-bearing field values: names, emails, logins, phone numbers, personnel ids.
- Full file contents, sample rows, DataFrame dumps.
- Absolute paths if deployment layout is sensitive; prefer logical location or relative path where possible.

### Что уже легко заполнить при внедрении

- `SourceSpec.source` already provides type, format, location, has_header and CSV options.
- `resolve_source_location()` already returns runtime path and can populate `source-resolved`.
- `CsvRecordSource` already knows path, delimiter, encoding, header mode, line numbers and field counts.
- `parse_null()` makes null counters cheap to compute during row materialization.
- `CsvFormatError` messages already include line number and expected/actual column counts for mismatch;
  structured fields can be added without changing domain semantics.
- `Extractor.run()` already has the `SOURCE_ERROR` boundary and can populate `source-stream-failed`.

### Что останется на будущие зоны

- Source-side topology adjacency ingestion and anchoring — topology taxonomy.
- Mapping rules that consume `SourceRecord.values` — mapping taxonomy.
- Normalize data quality and type coercion — Zone 14.
- DSL source spec loading/validation internals — Zone 7.

---
