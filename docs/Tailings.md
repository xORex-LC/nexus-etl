Идеи на потом:

1) Держать документацию RequestExecutorProtocol в духе no-throw (синхронизировать док/контракт).
2) Ввести прослойку SourceMapper между reader и validator: разделить физический reader (CSV/DB/API) и маппер, который приводит данные к унифицированному CsvRow.
3) Убрать legacy-поля из cache refresh отчёта: entity_type заменить на dataset (поле entity_type сейчас сохраняется как след старой entity-архитектуры).
4) Унифицировать cache-репозиторий: перейти от dataset-specific методов (upsert_user/upsert_org) к общему upsert(dataset, row) после стабилизации.
5) Вынести employees-lookup из planning/adapters в общий cache↔dataset порт (сделать lookup strategy для датасетов вместо CacheEmployeeLookup).
6) Проверить необходимость runtime-обёрток plan_runtime (ResolvedPlan/ResolvedPlanItem) после фикса meta.dataset как единственного источника.
7) Убрать infra-утечку retries_used в CacheRefreshUseCase: добавить метод в TargetPagedReaderProtocol или прокинуть значение через порт, когда будем делать полноценный рефактор cache-слоя.
8) Оставить legacy-метрики cache refresh (inserted_users/updated_users/pages_users и т.п.) до перехода на dataset-agnostic summary; при рефакторе заменить на summary.by_dataset и удалить legacy поля.
9) Убрать функциональные утилиты infra/cache/repo.py после ввода общего cache↔dataset lookup-порта (сейчас используется CacheEmployeeLookup/findUsersByMatchKey).
