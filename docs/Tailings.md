Идеи на потом:

1) Держать документацию RequestExecutorProtocol в духе no-throw (синхронизировать док/контракт).
2) Ввести прослойку SourceMapper между reader и validator: разделить физический reader (CSV/DB/API) и маппер, который приводит данные к унифицированному CsvRow.
3) Унифицировать cache-репозиторий: перейти от dataset-specific методов (upsert_user/upsert_org) к общему upsert(dataset, row) после стабилизации.
4) Вынести employees-lookup из planning/adapters в общий cache↔dataset порт (сделать lookup strategy для датасетов вместо CacheEmployeeLookup).
5) Проверить необходимость runtime-обёрток plan_runtime (ResolvedPlan/ResolvedPlanItem) после фикса meta.dataset как единственного источника.
6) Убрать infra-утечку retries_used в CacheRefreshUseCase: добавить метод в TargetPagedReaderProtocol или прокинуть значение через порт, когда будем делать полноценный рефактор cache-слоя.
7) Убрать legacy-утилиты infra/cache/legacy_queries.py после ввода общего cache↔dataset lookup-порта (сейчас используется CacheEmployeeLookup/findUsersByMatchKey).
8) Добавить тесты на реальный HTTP-стек (AnkeyRequestExecutor + AnkeyApiClient), чтобы ловить регрессии по параметрам/таймаутам/маппингу ошибок.
9) Сделать CSV-источник универсальным (убрать жёсткую привязку к employees-схеме в csv_reader).
10) Убрать dataset-импорты из domain validation (employees projector в домене) — вынести в DatasetSpec.
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
25) TODO: удалить legacy EmployeeInput/RowValidator adapter после миграции пайплайна на public rows (PrepareForSink).
26) TODO: убрать EmployeesCsvRecordAdapter (datasets/employees/csv_record_adapter.py) после перевода extract-слоя на SourceRecord для всех источников.
27) TODO: TECHDEBT — убрать CsvRow из источников (использовать SourceRecord напрямую после extract/transform).
28) TODO: TECHDEBT — вынести FIELD_RULES (employees CSV schema) из domain в datasets/employees/field_rules.py.
29) TODO: TECHDEBT — password не должен быть required на source-parse; перенести обязательность на sink/create после enrich.
30) TODO: TECHDEBT — подчистить legacy-импорты/структуру в validation pipeline после рефакторинга.
31) TODO: TECHDEBT — перенести запись секретов из PlanUseCase в Enricher/SecretsPolicy после внедрения enrich-слоя.
32) TODO: TECHDEBT — убрать вырезание маскированного password в plan_reader после перехода на secret_fields-only.
33) TODO: TECHDEBT — перенести построение/проверку match_key из SourceMapper на этап после transform/enrich.
34) TODO: TECHDEBT — удалить LegacyRowSource/RowMapper (CsvRow) после полного перехода на SourceRecord.
35) Убрать двойную истину для counts: meta.users_count/org_count vs реальные COUNT(*) — определить единый источник и инвариант обновления (транзакционно).
36) Усилить типизацию DTO на границах (MapResult/CollectResult/SourceRecord/Normalized/Enriched) — заменить dict/Any на dataclass/TypedDict для контрактов.
37) Версионировать миграции SQLite (registry/файлы), чтобы порядок изменений был воспроизводим и тестируем.

Sink-spec leakage (where sink/normalized specificity leaks into non-dataset layers):
- connector/infra/sources/csv_reader.py: EXPECTED_COLUMNS=14 (employees-only нормализованный CSV).

Sink-spec in correct place (dataset layer, ok):
- connector/datasets/employees/field_rules.py: employees CSV schema и required-правила.
- connector/datasets/employees/source_mapper.py: маппинг SourceRecord -> EmployeesRowPublic.
- connector/datasets/employees/projector.py: desired_state/source_ref/identity для employees.
- connector/datasets/employees/planning_policy.py: employees decision + desired_state.
- connector/datasets/employees/apply_adapter.py: построение request payload для sink.
- connector/datasets/employees/spec.py: wiring employees dataset components.
- connector/datasets/employees/csv_record_adapter.py: employees CSV -> SourceRecord.
