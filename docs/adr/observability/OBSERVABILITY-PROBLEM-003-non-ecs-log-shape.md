# OBSERVABILITY-PROBLEM-003: JSON-логи структурированы, но не в формате ECS

> **Статус**: Открыто
> **Дата**: 2026-06-09
> **Слой**: Observability (logging)
> **Связанные решения**: [OBSERVABILITY-DEC-001](./OBSERVABILITY-DEC-001-structlog-as-standard.md), [OBSERVABILITY-DEC-002](./OBSERVABILITY-DEC-002-per-component-prod-observability-layout.md)

---

## 📋 Контекст

После [DEC-002](./OBSERVABILITY-DEC-002-per-component-prod-observability-layout.md) логирование переведено
на structlog с per-component раскладкой и dual transport (человекочитаемый текст → файл/консоль,
JSON → stderr). JSON-вывод **структурирован и корректен**, но форма полей — **внутренняя**, не
соответствует [Elastic Common Schema (ECS)](https://www.elastic.co/docs/reference/ecs/ecs-field-reference).

Сейчас один JSON-рекорд (см. `_build_structlog_processors` в
`connector/infra/logging/runtime.py`) выглядит примерно так:

```json
{
  "run_id": "…", "pipeline_run_id": "…", "component": "planner", "dataset": "employees",
  "event": "Cache refresh started", "level": "info",
  "timestamp": "2026-06-09T10:00:00.123456+00:00",
  "schema_version": "1.0", "host": "…", "pid": 1234,
  "scope": "cache", "stage": "enrich"
}
```

ECS ожидает иные имена и группировку: `@timestamp`, `message`, `log.level`, `log.logger`,
`event.*`, `labels.*`, `service.*`, `process.*`, `error.*`, `ecs.version`.

---

## ❗ Почему это проблема

Цель — будущая интеграция с Elasticsearch (Filebeat/Elastic Agent → ES → Kibana).

- ❌ **Несовместимость с готовой экосистемой ES.** Индексные шаблоны, dashboards и detection-правила
  Elastic построены вокруг ECS-полей. Наши имена (`event` вместо `message`, плоский `level` вместо
  `log.level`) не подхватятся автоматически.
- ❌ **Маппинг переносится на сторону ES.** Без ECS на источнике приходится держать ingest-pipeline в
  ES, который переименовывает поля. Это дублирование логики, дрейф между источником и кластером,
  лишняя точка отказа.
- ❌ **`event` как ключ сообщения конфликтует с ECS.** В ECS `event` — это объект (`event.action`,
  `event.outcome`, …), а у нас `event` — строка-сообщение. Прямая отправка ломает маппинг типов в ES
  (object vs keyword).
- ❌ **Нет `event.action`/`event.outcome`/`event.duration`.** Невозможно строить в Kibana
  lifecycle-аналитику (длительность стадий, success/failure rate) без верботного парсинга `message`.
- ❌ **Несогласованность call-sites.** Где-то `message` человекочитаемый («Cache status failed»),
  где-то event-code («vault_mgmt_init»); ключи разнятся (`scope` / `component` / `op`). Это усложняет
  фильтрацию и переход к ECS.

---

## 🔍 Что НЕ является проблемой (и менять не нужно)

- ✅ Транспорт и раскладка ([DEC-002](./OBSERVABILITY-DEC-002-per-component-prod-observability-layout.md)):
  per-component, dual transport, ротация, ledger, retention, latest pointers — остаются как есть.
- ✅ Корреляция через `bind_observability_context` (contextvars) — `run_id`/`pipeline_run_id`/
  `component`/`dataset` уже инжектируются в каждый рекорд.
- ✅ Redaction (`LogRedactionEngine`) — единая точка маскирования.
- ✅ Текстовые синки (human console, logfmt-файл) — они для людей, ECS им не требуется.

Проблема локальна: **форма финального JSON-рекорда**, а не архитектура подсистемы.

---

## 🎯 Желаемое состояние

JSON-синки эмитят валидный ECS-рекорд (dotted-ключи), пригодный для прямой отправки в ES без
ingest-переименований; человекочитаемые синки не меняются; call-sites остаются эргономичными.

→ Решение: [OBSERVABILITY-DEC-003](./OBSERVABILITY-DEC-003-ecs-renderer-and-field-mapping.md).
