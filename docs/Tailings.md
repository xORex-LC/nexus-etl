Идеи на потом:

1) Держать документацию RequestExecutorProtocol в духе no-throw (синхронизировать док/контракт).
2) Ввести прослойку SourceMapper между reader и validator: разделить физический reader (CSV/DB/API) и маппер, который приводит данные к унифицированному CsvRow.
3) Унифицировать cache-репозиторий: перейти от dataset-specific методов (upsert_user/upsert_org) к общему upsert(dataset, row) после стабилизации.
4) Вынести employees-lookup из planning/adapters в общий cache↔dataset порт (сделать lookup strategy для датасетов вместо CacheEmployeeLookup).
5) Проверить необходимость runtime-обёрток plan_runtime (ResolvedPlan/ResolvedPlanItem) после фикса meta.dataset как единственного источника.
6) Убрать infra-утечку retries_used в CacheRefreshUseCase: добавить метод в TargetPagedReaderProtocol или прокинуть значение через порт, когда будем делать полноценный рефактор cache-слоя.
7) Убрать legacy-утилиты infra/cache/legacy_queries.py после ввода общего cache↔dataset lookup-порта (сейчас используется CacheEmployeeLookup/findUsersByMatchKey).
