# Outcome, Kind, and Maintenance Rules

- **`event.outcome`** (`EventOutcome`): `success` | `failure` | `unknown`. Ставится на событиях
  завершения (`*-completed`, `run-completed`, любые `*-failed` → `failure`).
- **`event.kind`** (`EventKind`): `event` (default) | `metric` (числовые замеры — длительности, счётчики
  как самостоятельное событие) | `state` (снимок состояния). Если не указан — `event`.

---

## 🛠️ Как пополнять

**Добавить ECS-поле:**
1. Добавить строку в таблицу маппинга в `ecs.py` (внутренний ключ → ECS-таргет) либо осознанно оставить
   в `labels.*`.
2. Добавить строку в [Field Catalog](./field-catalog.md).
3. Обновить вендоренный срез ECS-полей в тесте, если поле новое для схемы.

**Добавить `event.action`:**
1. Добавить член в `EventAction` (StrEnum) в `ecs.py`.
2. Добавить строку в [Event Action Dictionary](./event-action-dictionary.md) с уровнем и контекстом.
3. Использовать на call-site: `logger.info("…", action=EventAction.MY_ACTION, …)`.

**Нельзя:** изобретать корневые не-ECS ключи на call-site — всё неучтённое обязано уходить в `labels.*`
(контрактный тест «нет неизвестных корневых ключей» это ловит).

---

## 🔗 Связанные документы

- [observability-logging.md](../observability-logging.md) — runtime, процессоры, redaction surface, sinks
- [OBSERVABILITY-DEC-003](../../../../adr/observability/OBSERVABILITY-DEC-003-ecs-renderer-and-field-mapping.md) — решение, маппинг, поддержание совместимости
- [OBSERVABILITY-PROBLEM-003](../../../../adr/observability/OBSERVABILITY-PROBLEM-003-non-ecs-log-shape.md) — проблема (не-ECS форма)
- `connector/infra/logging/ecs.py` — машинно-авторитетный источник (маппинг + enum'ы)
- [ECS Field Reference](https://www.elastic.co/docs/reference/ecs/ecs-field-reference) — внешний канон ECS
