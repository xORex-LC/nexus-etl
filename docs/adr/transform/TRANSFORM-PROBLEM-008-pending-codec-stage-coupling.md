# TRANSFORM-PROBLEM-008: pending_codec привязан к стадии resolver

> **Статус**: Открыто
> **Дата**: 2026-02-23
> **Затронутые компоненты**: `connector/domain/transform/resolver/pending_codec.py`, `connector/domain/transform/resolver/resolve_core.py`

---

## Проблема

`pending_codec.py` размещён в `resolver/` как прагматичный компромисс при реализации PLANNER-DEC-001: пакет `resolver/` содержал симметричную пару — `_serialize_pending_payload()` в `resolve_core.py`, — поэтому `pending_codec` разместили рядом.

Однако сериализация и десериализация pending payload — это **self-contained codec для lifecycle pending-ссылок**, не часть алгоритма resolve-стадии. Текущее расположение создаёт ложную связь между двумя независимыми концепциями:

- `resolver/` — алгоритм разрешения идентичностей (resolve-стадия pipeline)
- pending payload codec — формат сериализации отложенных строк для replay

**Следствия:**
- Будущий consumer pending payload за пределами resolve-стадии (retry-worker, scheduler, `PlanningPipeline` из TRANSFORM-DEC-006) получит зависимость на `resolver/`
- Пара сериализации (`resolve_core._serialize_*` + `pending_codec.load_*`) размазана по двум концептуально разным модулям
- SRP нарушен: пакет `resolver/` решает две независимые задачи — resolve-алгоритм и pending payload format

## Критерий решения

`pending_codec` (и оба конца пары — serialize + deserialize) живёт в пакете, ответственность которого — **формат pending payload**, без привязки к конкретной стадии.
