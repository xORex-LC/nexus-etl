# Call-Site Map

Выведено из всех 92 логирующих call-sites (`pytest`/README исключены). Это источник, из которого
наполняется `EventAction` в Фазе 2. **Курсивный `message`** — сейчас это event-код; по правилу Темы 3
он станет человекочитаемым, а код переедет в `event.action`. `outcome`: `—` = не завершающее событие.

### Run / orchestrator lifecycle (`component` = команда)
| Call-site | Lvl | message сейчас | event.action | outcome |
|---|---|---|---|---|
| orchestrator.py:403,743 | info | Command started | `run-started` | — |
| orchestrator.py:539,831 | error | Command failed | `run-failed` | failure |
| orchestrator.py:468,784 | error | Settings error | `config-load-failed` | failure |
| orchestrator.py:494,802 | error | DSL load error | `dsl-load-failed` | failure |
| orchestrator.py:514,814 | error | Runtime validation error | `runtime-validation-failed` | failure |
| orchestrator.py:857 | info | Log written | `log-written` | success |
| orchestrator.py:1056 | info | Report written | `report-written` | success |
| orchestrator.py:1058 | error | Report finalization failed | `report-finalize-failed` | failure |
| orchestrator.py:929,950 | error | Container *init failed | `container-init-failed` | failure |
| orchestrator.py:940 | error | Vault startup error | `vault-startup-failed` | failure |
| orchestrator.py:983 | error | Container shutdown failed | `container-shutdown-failed` | failure |
| orchestrator.py:992 | error | Container shutdown completed with errors | `container-shutdown-completed` | failure |

### Observability best-effort (`component` = observability/команда)
| Call-site | Lvl | message сейчас | event.action | outcome |
|---|---|---|---|---|
| orchestrator.py:252 | warning | Observability sweep failed | `retention-sweep-failed` | failure |
| orchestrator.py:1133,1182 | warning | Ledger record assembly failed | `ledger-record-failed` | failure |
| orchestrator.py:1206 | warning | Ledger append failed | `ledger-append-failed` | failure |
| orchestrator.py:1247,1282 | warning | Latest pointer update failed | `pointer-publish-failed` | failure |
| maintenance_prune.py:98 | info | Manual prune completed | `retention-prune-completed` | success |
| maintenance_prune.py:106 | error | Manual prune failed | `retention-prune-failed` | failure |
| obs_artifacts.py:87 | info | Displayed latest artifact | `artifact-view` | success |
| obs_artifacts.py:96 | error | Observability latest failed | `artifact-view` | failure |
| obs_artifacts.py:147 | info | Displayed artifact tail | `artifact-tail` | success |
| obs_artifacts.py:157 | error | Observability tail failed | `artifact-tail` | failure |

### Commands: plan / apply / api (`component` = planner/applier/topology)
| Call-site | Lvl | message сейчас | event.action | outcome |
|---|---|---|---|---|
| import_plan.py:223 | info | Plan written | `plan-written` | success |
| import_plan.py:240 | error | Import plan failed | `plan-build-failed` | failure |
| import_apply.py:110 | error | Import apply failed | `apply-failed` | failure |
| import_apply.py:180 | error | Failed to init identity index | `identity-init-failed` | failure |
| check_api.py:43 | info | API check succeeded | `api-check-completed` | success |
| check_api.py:61 | error | API check failed | `api-check-completed` | failure |
| cache_refresh.py:126 | error | Cache refresh failed | `cache-refresh-failed` | failure |
| common.py:29,45 | error | Failed to open cache DB | `cache-open-failed` | failure |
| common.py:60 | error | Vault startup error | `vault-startup-failed` | failure |

### Apply per-item (`component` = applier; `delivery/telemetry/apply_logging_sink.py`)
| Call-site | Lvl | message сейчас | event.action | outcome |
|---|---|---|---|---|
| :30 | debug | Apply item succeeded | `apply-item` | success |
| :39 | warning | Apply item warning | `apply-item` | unknown |
| :49 | error | Apply item failed | `apply-item` | failure |
| :64 | info | Apply summary | `apply-completed` | success |

### Cache usecases (`component` = cache)
| Call-site | Lvl | message сейчас | event.action | outcome |
|---|---|---|---|---|
| cache_refresh_service.py:87 | info | Cache refresh started | `cache-refresh-started` | — |
| cache_refresh_service.py:154 | debug | Target page fetched | `cache-page-fetched` | success |
| cache_refresh_service.py:229 | error | Failed to upsert cache item | `cache-upsert-failed` | failure |
| cache_refresh_service.py:298 | error | Cache refresh failed | `cache-refresh-failed` | failure |
| cache_refresh_service.py:338 | info | Cache refresh completed | `cache-refresh-completed` | success |
| cache_command_service.py:94 | error | Cache status failed | `cache-status-failed` | failure |
| cache_command_service.py:120 | info | Cache clear completed | `cache-clear-completed` | success |
| cache_command_service.py:134 | error | Cache clear failed | `cache-clear-failed` | failure |

### Vault management (`component` = vault; messages — коды → станут человеческими)
| Call-site | Lvl | message сейчас | event.action | outcome |
|---|---|---|---|---|
| management/vault/usecase.py:85 | info | *vault_mgmt_init* (op=start) | `vault-init-started` | — |
| management/vault/usecase.py:118 | info | *vault_mgmt_init* (op=success) | `vault-init-completed` | success |
| management/vault/usecase.py:169 | info | *vault_mgmt_rotate* (op=start) | `vault-rotate-started` | — |
| management/vault/usecase.py:198 | info | *vault_mgmt_rotate* (op=success) | `vault-rotate-completed` | success |
| management/vault/usecase.py:222 | info | *vault_mgmt_rewrap* | `vault-rewrap-started` | — |

### Vault admin gate (`infra/secrets/admin_password_gate.py`; `component` = vault)
| Call-site | Lvl | message сейчас | event.action | outcome |
|---|---|---|---|---|
| :124 | info | *vault_admin_password_gate_skipped* | `admin-gate-skipped` | — |
| :140 | info | *vault_admin_password_gate_passed* | `admin-gate-passed` | success |
| :152–402 (14×) | warn/error | *vault_admin_password_gate_failed* | `admin-gate-failed` | failure |

### Dictionary (`component` = enricher, `scope` = dictionary; `infra/dictionaries/telemetry.py`)
| Call-site | Lvl | message сейчас | event.action | outcome |
|---|---|---|---|---|
| :133 | debug | *lookup_hit* / *lookup_miss* (динам.) | `dictionary-lookup` | success (hit/miss → `labels`) |
| :186 | warning | *source_empty* | `dictionary-source-empty` | unknown |
| :216 | warning | *lookup_error* | `dictionary-lookup` | failure |
| record_runtime_initialized | info | (runtime init) | `dictionary-initialized` | success |

### Target driver (`component` = applier; `infra/target/core/engines/safe_logging.py`)
| Call-site | Lvl | message сейчас | event.action | outcome |
|---|---|---|---|---|
| :87 | warning | target request failed | `target-request-failed` | failure |
| :102 | debug | запланирован повтор target-операции | `retry-attempt` | — |

### Прочие (domain/usecases)
| Call-site | Lvl | message сейчас | event.action | outcome |
|---|---|---|---|---|
| resolve_core.py:200 | warning | merge_policy tried to overwrite… (`%s`-стиль!) | `merge-conflict` | unknown |
| resolve_usecase.py:83 | warning | *pending_codec_skipped_invalid* | `pending-decode-skipped` | unknown |
| infra/cache/dsl_adapter.py:129 | warning | cache sync value expr issue (`%s`-стиль!) | `cache-sync-issue` | unknown |

### Форвардеры логов (динамический уровень — `event.action` от вызывающего, не фикс.)
| Call-site | Назначение | Примечание |
|---|---|---|
| infra/logging/topology.py:47–55 | `StructlogTopologyEventSink._dispatch_log` | топология эмитит свой `event`/`level`; action — у вызывающего |
| delivery/cli/stream_capture.py:120–128 | перехват stdout/stderr | `event.action`=`captured-stream`, `event.kind`=`event` |

> Найдено попутно (вне ECS-скоупа, в worknote): `resolve_core.py:200` и `dsl_adapter.py:129` используют
> **stdlib `%s`-форматирование** вместо structlog kwargs — их надо привести к structlog при наполнении.

---
