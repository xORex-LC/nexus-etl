# Event Action Dictionary

Канонический список — `EventAction` (StrEnum) в `ecs.py`. Значения — `verb-noun`, kebab-case. Описания:

| Действие | Уровень | Контекст |
|---|---|---|
| `run-started` | INFO | Старт прогуна команды/пайплайна |
| `run-completed` | INFO | Завершение прогона с `event.outcome` |
| `stage-started` | INFO | Старт стадии пайплайна |
| `stage-completed` | INFO | Завершение стадии с `event.outcome`+`event.duration` |
| `stage-failed` | ERROR | Стадия упала с необработанным исключением |
| `spec-loaded` / `spec-registry-built` / `spec-validation-failed` | DEBUG/INFO/ERROR | Legacy/compat generic spec actions; новый путь использует `dsl-*` |
| `dsl-registry-loaded` / `dsl-registry-built` | DEBUG/INFO | DSL registry загружен/собран |
| `dsl-registry-build-failed` | ERROR | Сборка DSL registry завершилась ошибкой |
| `dsl-spec-discovered` | TRACE | DSL spec artifact найден |
| `dsl-spec-loaded` | DEBUG | DSL spec YAML загружен |
| `dsl-spec-parsed` | TRACE/DEBUG | DSL spec разобран из YAML |
| `dsl-spec-validated` | DEBUG | DSL spec прошёл validation |
| `dsl-spec-compiled` | DEBUG | DSL spec скомпилирован в runtime object |
| `dsl-load-failed` | ERROR | Чтение DSL файла или YAML parse завершились ошибкой |
| `dsl-validation-failed` | ERROR | Structural/semantic validation DSL spec завершилась ошибкой |
| `dsl-compile-failed` | ERROR | Валидный DSL spec не удалось скомпилировать в runtime object |
| `match-record-completed` | DEBUG | Match сформировал typed decision для записи |
| `match-record-failed` | DEBUG/ERROR | Match не смог сформировать корректный row-level result |
| `match-identity-resolved` | TRACE | Identity rule дала usable identity |
| `match-fuzzy-ranked` | TRACE | Fuzzy candidates были ranked/scored |
| `match-topology-refined` | DEBUG/TRACE | Topology уточнила match decision |
| `match-source-dedup-checked` | TRACE | Source dedup check завершён |
| `match-source-dedup-dropped` | DEBUG/WARNING/ERROR | Source dedup policy дропнула запись |
| `match-scope-cleared` / `match-scope-clear-failed` | DEBUG/WARNING | Runtime scope matcher очищен/не очищен |
| `resolve-context-index-built` | DEBUG | ResolveContext построил batch index |
| `resolve-record-completed` | DEBUG | Resolve сформировал operation decision для записи |
| `resolve-record-failed` | DEBUG/ERROR | Resolve не смог сформировать корректный row-level result |
| `resolve-op-selected` | TRACE/DEBUG | Выбрана операция `create`/`update`/`skip` |
| `resolve-link-completed` | DEBUG/TRACE | Link field resolved/pending/ambiguous/missing |
| `resolve-link-pending-created` | DEBUG/WARNING | Создан pending link для unresolved link field |
| `resolve-link-max-attempts-reached` | WARNING/ERROR | Pending link достиг max attempts |
| `resolve-pending-replayed` | DEBUG | Pending rows загружены для replay |
| `pending-decode-skipped` | WARNING | Invalid pending rows skipped during replay |
| `resolve-pending-expired` | DEBUG/WARNING/ERROR | Expired pending обработан по policy |
| `resolve-pending-purged` | DEBUG | Stale pending rows удалены retention purge |
| `resolve-merge-overwrite-blocked` | WARNING | Merge policy tried to overwrite source values |
| `plan-build-started` / `plan-build-completed` | INFO/DEBUG | Сборка plan началась/завершилась |
| `plan-build-failed` | ERROR | Сборка plan завершилась ошибкой |
| `plan-item-created` | TRACE/DEBUG | Plan item добавлен в artifact payload |
| `plan-item-skipped` | DEBUG | Resolved row skipped, plan item не создан |
| `plan-item-failed` | DEBUG | Resolved result excluded from plan due to errors |
| `plan-written` / `plan-write-failed` | INFO/ERROR | Plan artifact записан/не записан |
| `apply-started` | INFO | Старт apply-цикла по готовому plan artifact |
| `apply-item` | DEBUG/WARNING/ERROR | Per-item outcome apply use-case |
| `apply-completed` | INFO/ERROR | Apply summary завершён с агрегированным outcome |
| `cache-hit` / `cache-miss` | DEBUG | Legacy/compat результат кэш-лукапа; новый provider path — `lookup-completed` |
| `cache-refresh-started` / `cache-refresh-completed` | INFO | Старт/завершение cache refresh |
| `cache-refresh-failed` | ERROR | Cache refresh завершился ошибкой |
| `cache-refresh-dataset-completed` | DEBUG | Refresh одного cache dataset завершён |
| `cache-page-fetched` | DEBUG/TRACE | Target page получена во время cache refresh |
| `cache-item-upserted` | TRACE | Один source item записан в cache snapshot |
| `cache-item-upsert-failed` | ERROR/DEBUG | Ошибка записи одного source item в cache snapshot |
| `cache-clear-completed` / `cache-clear-failed` | INFO/ERROR | Очистка cache завершена/провалена |
| `cache-status-completed` / `cache-status-failed` | INFO/ERROR | Получение cache status завершено/провалено |
| `cache-drift-detected` | WARNING | Несовпадение content-hash кэша |
| `cache-rebuild-completed` / `cache-rebuild-failed` | INFO/ERROR | Cache rebuild завершён/провален |
| `vault-runtime-evaluated` | INFO/ERROR | Runtime intent для vault-path вычислен |
| `vault-rollout-evaluated` | INFO/ERROR | Rollout gate для vault-path вычислен |
| `vault-startup-completed` | INFO | Vault startup guard успешно завершён |
| `vault-startup-failed` | ERROR | Vault startup guard / key validation завершились ошибкой |
| `target-write-started` / `target-write-completed` | DEBUG | Lifecycle одной target write-операции |
| `target-write-failed` | ERROR | Запись в цель провалилась после retry или без retry-path |
| `target-request-failed` | WARNING | Отдельная неуспешная target attempt до финального результата |
| `retry-attempt` | DEBUG | Запланирован повтор target-операции |
| `record-skipped` | WARNING | Запись отброшена (с причиной) |
| `enrich-record-completed` | DEBUG | Enrich обработал одну запись и сформировал summary |
| `enrich-operation-completed` | TRACE | Enrich operation/rule выполнена для записи |
| `enrich-operation-skipped` | DEBUG | Enrich operation/rule пропущена по policy/condition |
| `enrich-resolve-requested` | DEBUG | Enrich создал resolve hint из неоднозначных candidates |
| `enrich-secret-fields-stored` | DEBUG | Enrich записал secret fields в vault и очистил row values |
| `lookup-started` / `lookup-completed` | TRACE/DEBUG | Provider lookup/exists/canonicalize в cache/dictionary/vault context |
| `identity-lookup-completed` | DEBUG | Identity index lookup завершён |
| `identity-upsert-completed` | DEBUG | Identity index обновлён после resolve/apply |
| `identity-source-resolved` | DEBUG | Source record помечена как resolved |
| `pending-link-created` | DEBUG | Resolve создал pending link |
| `pending-link-touched` | TRACE | Pending link получил новую попытку обработки |
| `pending-link-resolved` | DEBUG | Pending link разрешён |
| `pending-link-expired` | DEBUG/WARNING | Pending link истёк по TTL/policy |
| `pending-link-conflicted` | DEBUG/WARNING | Pending link переведён в conflict |
| `storage-operation-failed` | WARNING/ERROR | Storage backend operation завершилась ошибкой |
| `secret-read` / `secret-written` | DEBUG/ERROR | Runtime read/write секретов без plaintext значений |
| `secret-retention-completed` | DEBUG | Post-apply cleanup lifecycle секретов завершён |
| `secret-maintenance-completed` | DEBUG | Best-effort maintenance hooks vault runtime завершены |
| `config-loaded` | INFO | `AppConfig` валидирован и загружен |
| `container-initialised` | INFO | DI-контейнер собран |

> Список выше — **целевой lifecycle-словарь**. Фактический `EventAction` (StrEnum) строится из
> [call-site map](./callsite-map.md), выведенной из реального кода.

---
