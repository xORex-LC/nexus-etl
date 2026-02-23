# TRANSFORM-DEC-008: Вынести pending_codec в отдельный feature-пакет

> **Статус**: Отложено
> **Дата**: 2026-02-23
> **Решает проблему**: [TRANSFORM-PROBLEM-008](./TRANSFORM-PROBLEM-008-pending-codec-stage-coupling.md)
> **Зависит от**: ничего (независимо от TRANSFORM-DEC-006/007)
> **Участники решения**: @xorex-LC

---

## Решение

Переместить `pending_codec.py` и `_serialize_pending_payload()` в отдельный feature-пакет внутри domain — **не новый application layer**, а отдельная фича с единственной ответственностью: формат pending payload.

### Целевая структура

```
connector/domain/transform/pending/
    __init__.py
    codec.py      # load_pending_rows() + _serialize_pending_payload()
```

`resolve_core.py` импортирует `pending.codec._serialize_*`.
`ResolveUseCase` импортирует `pending.codec.load_pending_rows`.
Любой будущий consumer импортирует напрямую из `pending.codec`.

### Что не меняется

- Публичный API: `load_pending_rows(list[PendingRow]) -> PendingLoadResult` — без изменений
- Порты: `ResolveRuntimePort.list_pending_rows()` — без изменений
- Тесты в `tests/unit/resolver/test_pending_codec.py` — путь импорта обновляется, логика не меняется

---

## Когда реализовать

При наступлении **одного** из условий:

1. Появился второй consumer pending payload за пределами `resolver/` (retry-worker, scheduler, `PlanningPipeline` из TRANSFORM-DEC-006)
2. Принято решение перенести `_serialize_pending_payload()` из `resolve_core.py` — тогда обе стороны пары объединяются в `pending/codec.py`

До тех пор текущее расположение в `resolver/` является допустимым временным решением с явно зафиксированным техдолгом (этот документ).
