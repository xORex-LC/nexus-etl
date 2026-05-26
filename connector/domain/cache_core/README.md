# connector/domain/cache_core

## Назначение

Чистая доменная логика управления кэшем: планирование обновления, анализ drift, управление зависимостями между датасетами. Не содержит SQL и не работает с файлами.

## Ключевые компоненты

| Файл | Класс | Назначение |
|---|---|---|
| `lifecycle.py` | `CacheLifecycleEngine` | Оркестрирует операции refresh/clear/status поверх портов |
| `refresh_planner.py` | `CacheRefreshPlanner` | Определяет порядок и стратегию обновления датасетов |
| `clear_planner.py` | `CacheClearPlanner` | Планирование очистки с учётом зависимостей |
| `status_evaluator.py` | `CacheStatusEvaluator` | Оценка состояния кэша (актуален/устарел/пуст) |
| `drift_service.py` | `CacheDriftService` | Проверка content-hash кэша; код ошибки `CACHE_DSL_HASH_MISMATCH` |
| `dependency_graph.py` | `CacheDependencyGraph` | Топологическая сортировка зависимостей датасетов (ADR: CACHE-DEC-001) |

## Зависимости

**Зависит от:** `domain/ports/cache/`, `domain/diagnostics/`.  
**Используется:** `usecases/cache_refresh_service.py`, `usecases/cache_command_service.py`.
