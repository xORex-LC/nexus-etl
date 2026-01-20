1. Внутри maskSecretsInObject каждый раз пересоздаётся генератор (key.lower() for key in sensitive_keys) — потом можно заменить на заранее посчитанный set
2. В RequestExecutorProtocol док сейчас допускает, что реализации могут бросать исключения, а AnkeyRequestExecutor по факту гарантирует no-throw.

Остатки старой архитектуры

1) connector/usecases/import_apply_service.py - всё ещё employees-only: UserApiProtocol, UserApi, buildUserUpsertPayload, PUT user, retry “resourceExists”, и т.д. Это главный кусок старого apply-ядра.
2) connector/domain/ports/api.py + connector/infra/http/user_api.py - сейчас они используются только в import_apply_service.py и тестах stage7. После перевода apply на RequestExecutorProtocol — станут кандидатами на удаление.
3) Тесты tests/test_stage7_import_apply.py - большая часть тестов завязана на DummyUserApi/UserApi. Их придётся перевести на DummyExecutor + dataset apply adapter.