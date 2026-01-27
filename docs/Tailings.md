Идеи на потом:

1) Держать документацию RequestExecutorProtocol в духе no-throw (синхронизировать док/контракт).
2) Ввести прослойку SourceMapper между reader и validator: разделить физический reader (CSV/DB/API) и маппер, который приводит данные к унифицированному SourceRecord (или typed row).
3) Унифицировать cache-репозиторий: перейти от dataset-specific методов (upsert_user/upsert_org) к общему upsert(dataset, row) после стабилизации.
4) Вынести employees-lookup из planning/adapters в общий cache↔dataset порт (сделать lookup strategy для датасетов вместо CacheEmployeeLookup).
5) Проверить необходимость runtime-обёрток plan_runtime (ResolvedPlan/ResolvedPlanItem) после фикса meta.dataset как единственного источника.
6) Убрать infra-утечку retries_used в CacheRefreshUseCase: добавить метод в TargetPagedReaderProtocol или прокинуть значение через порт, когда будем делать полноценный рефактор cache-слоя.
7) Убрать legacy-утилиты infra/cache/legacy_queries.py после ввода общего cache↔dataset lookup-порта (сейчас используется CacheEmployeeLookup/findUsersByMatchKey).
11) Разделить правила валидации на generic и dataset-специфичные (employees-правила в datasets/*).
12) Привести validate к usecase-архитектуре через DatasetSpec (как plan/apply), убрать employees-only wiring в main.py.
13) Упразднить дублирование реестров валидаторов (dataset/registry vs DatasetSpec.build_validators) — оставить один источник истины.
14) Убрать дублирование cache-реестров (cache_registry vs handlers.registry) — единая точка wiring.
15) Решить проблему дубля доступа к кэшу (legacy_queries vs repository) — миграция и удаление legacy.
16) Добавить стратегию очистки устаревших записей в cache refresh (GC/soft-delete/полный rebuild).
17) Разнести wiring/bootstrapping из main.py (сделать отдельный bootstrap/container).
18) Централизовать обработку ошибок/exit codes по командам.
19) Упростить модель отчётов: либо per-command schema, либо чёткое разделение секций.
20) Упростить настройку settings (единый декларативный источник, чтобы не править CLI/ENV/config в нескольких местах).
21) Нормально подключить SecretProvider варианты в CLI (env/file/dict/composite) или убрать неиспользуемые.
22) Ослабить хрупкие CLI-тесты (usage/help) — проверять стабильные подстроки или отключить rich.
23) Добавить тесты на PromptSecretProvider (интерактивный ввод).
24) Запланировать отдельный слой нормализации/обогащения (порт + адаптеры) для multi-source.
25) TODO: TECHDEBT — перенести запись секретов из PlanUseCase в Enricher/SecretsPolicy после внедрения enrich-слоя.
26) TODO: TECHDEBT — убрать вырезание маскированного password в plan_reader после перехода на secret_fields-only.
27) TODO: TECHDEBT — перенести построение/проверку match_key из SourceMapper на этап после transform/enrich.
28) TODO: TECHDEBT — password не должен быть required на source-parse; перенести обязательность на sink/create после enrich.
29) Убрать двойную истину для counts: meta.users_count/org_count vs реальные COUNT(*) — определить единый источник и инвариант обновления (транзакционно).
30) Усилить типизацию DTO на границах (SourceRecord/Normalized/Enriched) — заменить dict/Any на dataclass/TypedDict для контрактов.
31) Версионировать миграции SQLite (registry/файлы), чтобы порядок изменений был воспроизводим и тестируем.

Sink-spec leakage (where sink/normalized specificity leaks into non-dataset layers):
- (удалено) csv_reader.py (employees-only нормализованный CSV) — больше не используется.

Sink-spec in correct place (dataset layer, ok):
- connector/datasets/employees/source_mapper.py: маппинг SourceRecord -> EmployeesRowPublic.
- connector/datasets/employees/projector.py: desired_state/source_ref/identity для employees.
- connector/datasets/employees/planning_policy.py: employees decision + desired_state.
- connector/datasets/employees/apply_adapter.py: построение request payload для sink.
- connector/datasets/employees/spec.py: wiring employees dataset components.
