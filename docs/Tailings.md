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
26) TODO: убрать EmployeesCsvRecordAdapter после перевода extract-слоя на SourceRecord для всех источников.
