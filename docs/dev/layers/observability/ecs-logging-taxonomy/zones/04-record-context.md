# Zone 4: Record Context

Четвёртая рабочая зона taxonomy — общий контекст записи, который используется всеми
record-level событиями: diagnostics, reporting, enrich, match, resolve, plan/apply item telemetry.
Это не payload записи и не бизнес-сущность target system, а безопасная ссылка на исходную запись
и её путь через pipeline.

В текущей модели кода уже есть две близкие ссылки:

- `RowRef` в domain transform/diagnostics/reporting: `line_no`, `row_id`,
  `identity_primary`, `identity_value`.
- `RecordRef` в planning/apply: `row_id`, `line_no`.

Taxonomy объединяет их в один logging namespace `nexus.record.*`, чтобы apply, diagnostics и
pipeline stages не расходились в плоские `row_id`/`line_no`/`row_ref` labels.

### Принципы именно для этой зоны

- `nexus.record.*` отвечает только на вопрос **"о какой записи идёт речь?"**.
- `nexus.record.*` не содержит source row payload, raw field values, ФИО, email, login, табельный
  номер или secret evidence.
- Raw `RowRef.identity_value` не логируется. Если нужно связать события одной business identity,
  использовать `nexus.record.identity.value_fingerprint`.
- `nexus.record.id` — opaque pipeline/plan id. Он может быть `line:<n>`, UUID, source record id
  или id из plan item, но не должен трактоваться как business identity.
- `nexus.record.source.path` не является per-record обязательным полем. Его достаточно логировать
  на source lifecycle events или на редких диагностиках, где без пути невозможно разобраться.
- Если точной ссылки на запись нет, `nexus.record.*` не эмитится. Не надо подставлять фиктивные
  значения вроде `unknown`, кроме уже существующих domain sentinel values (`row_id="source"`).

### Canonical mapping из текущей модели

| Текущий источник | Logging field | Комментарий |
|---|---|---|
| `RowRef.row_id` | `nexus.record.id` | Основной record correlation key внутри transform/reporting/diagnostics |
| `RowRef.line_no` | `nexus.record.line_no` | Только для line-based источников |
| `RowRef.identity_primary` | `nexus.record.identity.primary` | Имя identity field безопасно логировать |
| `RowRef.identity_value` | `nexus.record.identity.value_fingerprint` | Только fingerprint; raw value запрещён |
| `RecordRef.row_id` | `nexus.record.id` | Apply/plan item использует тот же namespace |
| `RecordRef.line_no` | `nexus.record.line_no` | Apply/plan item сохраняет source line |
| `PlanItem.source_ref` | не маппить целиком | Может содержать source-specific data; нужны явные safe поля при необходимости |

### Минимальный field profile для record-level событий

| Поле | Статус | Примечание |
|---|---|---|
| `trace.id` | required | связывает record event с запуском |
| `event.dataset` | required when dataset-aware | business dataset |
| `nexus.stage.name` | expected inside pipeline stages | stage, где событие произошло |
| `nexus.subsystem` | recommended | subsystem, который принял решение |
| `nexus.record.id` | recommended | основной opaque record id |
| `nexus.record.line_no` | recommended when available | CSV/source line number |
| `nexus.record.identity.primary` | optional | только имя identity field |
| `nexus.record.identity.value_fingerprint` | optional | только safe fingerprint |
| `nexus.record.source.kind` | optional | `csv`, `plan`, `pending`, `api`, ... |
| `nexus.record.source.path` | sparse optional | source lifecycle / редкие diagnostics, не dense per-record stream |

### Detail policy для зоны

- `INFO` — не использовать для per-record context, кроме редких user-facing summary events.
- `DEBUG` — основной уровень для record-level decisions: skipped row, failed row, apply item,
  match decision, resolve decision, enrich record summary.
- `TRACE` — rule/field/provider детализация для конкретной записи; всегда дополняется
  `nexus.record.*`, если `RowRef`/`RecordRef` доступен.
- `WARNING`/`ERROR` — record context обязателен, если ошибка относится к конкретной записи и ссылка
  уже доступна в доменной модели.

### Что не логировать

- Raw `RowRef.identity_value`.
- Полный `row_ref` object без схемы.
- Source row payload, `SourceRecord.values`, `desired_state`, `changes`, full `PlanItem`.
- PII-поля: ФИО, email, login, phone, personnel number, document ids.
- Secret fields, generated passwords, vault key material.
- Raw lookup keys; для lookup использовать `nexus.lookup.key_fingerprint`.

### Связь с соседними зонами

- Enrich использует `nexus.record.*` как общий record context, а детали операции кладёт в
  `nexus.enrich.*`.
- Match использует `nexus.record.*` для source row, а candidate/target identity будет описывать
  отдельными match/cache fields.
- Resolve/plan/apply используют `nexus.record.*` для связи plan item с исходной записью.
- Reporting/diagnostics могут строить `nexus.record.*` из `DiagnosticItem.record_ref` и
  `ReportItem.row_ref`.

---
