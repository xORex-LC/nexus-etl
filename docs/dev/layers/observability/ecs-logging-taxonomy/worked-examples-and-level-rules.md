# Worked Examples and Level Rules

Каждая строка = **общая шапка** (всегда, из contextvars + runtime-meta) + **поля конкретного вызова**.
Шапка: `@timestamp, message, log.level, log.logger, trace.id, labels.pipeline_run_id,
service.name, service.type, service.version, host.name, process.pid, ecs.version`.

Ниже — реальные call-sites «как сейчас» → «ECS после `ecs_transform`».

### A. INFO — старт refresh кэша
Call-site ([cache_refresh_service.py:87](../../../../../connector/usecases/cache_refresh_service.py)):
`logger.info("Cache refresh started", scope="cache", page_size=…, max_pages=…, dataset=…)`
(команда `cache refresh` → контекст `component=cache`)
```json
{"@timestamp":"2026-06-10T08:00:01Z","message":"Cache refresh started","log.level":"info",
 "log.logger":"nexus.cache","event.action":"cache-refresh-started","event.dataset":"employees",
 "trace.id":"01J…","labels.pipeline_run_id":"01J…","service.name":"nexus-etl","service.type":"cache",
 "nexus.subsystem":"cache","labels.page_size":500,"labels.max_pages":20,"service.version":"1.4.0",
 "host.name":"etl-01","process.pid":4123,"ecs.version":"8.11"}
```

### B. DEBUG — lookup словаря (внутри enrich → `component=enricher`, `scope=dictionary`)
Call-site ([dictionaries/telemetry.py:133](../../../../../connector/infra/dictionaries/telemetry.py)):
сейчас `message` = код `"lookup_hit"`; в ECS код уходит в `event.action`, а `message` становится человеческим (см. правило Темы 3).
```json
{"@timestamp":"…","message":"Dictionary lookup hit","log.level":"debug","log.logger":"nexus.enricher",
 "event.action":"dictionary-lookup","trace.id":"01J…","service.type":"enricher",
 "nexus.subsystem":"dictionary","labels.dict_name":"departments","labels.op":"lookup","labels.backend":"polars",
 "labels.result_count":1,"ecs.version":"8.11"}
```

### C. ERROR — ошибка загрузки DSL-спеки (ручные error-kwargs, без `exc_info`)
Call-site ([orchestrator.py:494](../../../../../connector/delivery/cli/runtime/orchestrator.py)):
`logger.error("DSL load error", scope="dsl", diag_code=exc.code, error=str(exc), error_type=exc.__class__.__name__)`
```json
{"@timestamp":"…","message":"DSL load error","log.level":"error","log.logger":"nexus.planner",
 "event.action":"dsl-load-failed","event.outcome":"failure","error.type":"DslLoadError",
 "error.message":"…","error.code":"DSL_SPEC_INVALID","trace.id":"01J…","service.type":"planner",
 "nexus.subsystem":"dsl","nexus.dsl.phase":"load","ecs.version":"8.11"}
```

> Примеры A–C — целевой вид (Фаза 2, с `event.action`). В Фазе 1 ECS-форма уже валидна, но `event.action`
> ещё пуст для не-наполненных call-sites — действия проставляются по [call-site map](./callsite-map.md).

---

## 🎚️ Правила уровней

| Уровень | Когда | Обязательные поля |
|---|---|---|
| **CRITICAL** | Процесс не может продолжаться, аварийная остановка (DI/конфиг/необработанное на верхнем уровне) | `message`, `log.level`, `event.action`, `event.outcome=failure`, `error.*`, `trace.id` |
| **ERROR** | Прогон/значимая суб-операция упали (исключение или явный fail). Процесс может продолжиться, но этот прогон неуспешен | `message`, `event.action`, `event.outcome=failure`, `event.dataset`, `trace.id`, `nexus.stage.name`, `error.*` |
| **WARNING** | Неожиданное, но восстановимое; degraded-решение. Исключение не требуется | `message`, `event.action`, `event.dataset`, `trace.id`. **Без** `error.stack_trace`, если он не несёт диагностики |
| **INFO** | Значимое операционное событие. База в проде | `message`, `event.action`, `event.outcome` (на завершении), `event.dataset`, `event.duration` (на завершении), `trace.id`, `nexus.stage.name` (в стадии) |
| **DEBUG** | Подробная трассировка для разработчика (выкл. в проде) | `message`, `event.action`, `trace.id` + контекст, чтобы запись была самодостаточной |

**Минимум на прогон (INFO):** одно событие на старте прогона; старт+финиш каждой стадии (с `event.duration`
и счётчиком записей в `labels`); финиш прогона с `event.outcome`.

**Что НЕ логировать:** секреты/токены/пароли (их маскирует redaction, но и не передавать осознанно);
целые DataFrame'ы (только форму — высоту/колонки); одно и то же событие на двух уровнях; трейсбэки на WARNING.

---
