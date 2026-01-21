Чистка старья

1) Убрали UserApi/UserApiProtocol и перевели apply на RequestExecutor + dataset adapters.
2) Удалены устаревшие модули connector/infra/http/user_api.py и connector/domain/ports/api.py.

Идеи на потом

1) Держать документацию RequestExecutorProtocol в духе no-throw (синхронизировать док/контракт).
2) При необходимости убрать зависимость apply от DatasetSpec, сохранив “готовый” RequestSpec прямо в PlanItem или отдельной DTO.
