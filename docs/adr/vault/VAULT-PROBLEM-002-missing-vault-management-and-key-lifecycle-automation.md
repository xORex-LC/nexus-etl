# VAULT-PROBLEM-002: Отсутствует управляемый lifecycle master keys (user-management, rotate/rewrap, auto-rotation)

> **Статус**: Решена в [VAULT-DEC-002](./VAULT-DEC-002-vault-management-managed-env-keyring-and-rotation-lifecycle.md)
> **Дата создания**: 2026-03-04
> **Затронутые компоненты**: `EnvVaultKeyProvider`, `VaultStartupGuard`, `delivery/cli/app.py`, `delivery/cli/containers.py`, `config/models.py`, `usecases/management/vault/*`

---

## 📋 Контекст

Vault-подсистема уже использует envelope encryption и fail-fast startup guard ([VAULT-DEC-001](./VAULT-DEC-001-envelope-encrypted-vault-with-hexagonal-ports.md)).

Текущая модель master keys:
- ключи читаются из `ANKEY_VAULT_MASTER_KEYS`;
- первый ключ в keyring считается активным;
- startup guard блокирует запуск при ошибке keyring/probe.

При этом отсутствует production user-flow управления lifecycle ключей:
- нет встроенного bootstrap (инициализация ключа пользователем);
- нет команды безопасной ротации с обязательным re-wrap DEK;
- нет автоматической ротации по политике;
- нет управляемого persisted-источника keyring, пригодного для деплоя;
- нет manual-operation gate (пароль на операции управления vault).

Параллельно в продукте формируется operational-направление (`healthcheck`, `VACUUM`, maintenance). Без явного среза ответственности есть риск смешения этой orchestration-логики с доменным слоем `domain/secrets`.

---

## ⚠️ Проблема

Текущий vault-контур требует, чтобы пользователь заранее вручную сформировал корректный keyring в окружении процесса.

Это создаёт системный операционный разрыв:
- для первого запуска нет встроенного механизма инициализации;
- ротация в ручном режиме легко ломает decrypt-path (ошибка порядка/состава keyring);
- политика регулярной ротации не формализована в конфигурации и не исполняется автоматически;
- ключевой lifecycle не управляется единообразно через CLI приложения.
- при расширении operational-команд (healthcheck/vacuum/maintenance) растёт риск перегрузки `domain/secrets` эксплуатационной orchestration-логикой.

---

## 🔍 Симптомы

- **Симптом 1**: первый запуск vault-команд на чистом окружении падает с `VAULT_STARTUP_KEY_CONFIG_ERROR` (`reason=empty_keyring`).
- **Симптом 2**: ручная замена `ANKEY_VAULT_MASTER_KEYS` без fallback-ключа приводит к ошибкам decrypt/unwrap.
- **Симптом 3**: отсутствует безопасная команда `rotate + rewrap + verify`, операции выполняются ad-hoc.
- **Симптом 4**: невозможно задать и выполнить автоматическую ротацию по YAML-политике (часы/дни/месяцы/годы).
- **Симптом 5**: операции управления vault нельзя защитить паролем на уровне CLI, что повышает риск несанкционированных изменений.

---

## 📊 Масштаб проблемы

- **Частота**: Всегда для новых инсталляций и регулярно для production-эксплуатации (rotation window).
- **Критичность**: Высокая.
- **Затронуто**: `enrich`, `import plan`, `import apply` при включённом vault; DevOps-процессы деплоя и сопровождения.

---

## 🧪 Как воспроизвести

1. Подготовить чистое окружение без `ANKEY_VAULT_MASTER_KEYS`.
2. Запустить vault-path, например: `nexus import plan --vault-mode on`.
3. Наблюдать fail-fast на startup guard.
4. Далее вручную выставить один новый ключ, удалив старый fallback в существующей инсталляции.
5. **Ожидаемый результат**: контролируемая процедура `rotate + rewrap + verify`, совместимая с текущими данными.
6. **Фактический результат**: высокорисковая ручная операция; возможен сбой decrypt-path.

---

## 🚫 Почему это проблема?

- Нарушается операционная надёжность vault-контура при ротации.
- Усложняется безопасный rollout и сопровождение в production.
- Увеличивается риск простоев из-за ошибки keyring-конфигурации.
- Отсутствует единый управляемый путь lifecycle-операций через приложение.
- Нельзя централизованно включить policy-driven auto-rotation.

---

## 💡 Возможные решения (обсуждение)

> Этот раздел фиксирует варианты, рассмотренные до финального архитектурного решения

### Вариант 1: Только документация и ручные инструкции
- **Идея**: Оставить ENV-only и добавить runbook.
- **Плюсы**: Минимальные изменения кода.
- **Минусы**: Не устраняет операционные риски и человеческий фактор.

### Вариант 2: Добавить только `keygen`
- **Идея**: Сгенерировать ключ, но lifecycle (rotate/rewrap/auto) оставить ручным.
- **Плюсы**: Быстро снижает барьер первого запуска.
- **Минусы**: Основная проблема ротации остаётся нерешённой.

### Вариант 3: Полноценный `vault-management` с managed env-файлом (целевой)
- **Идея**: Встроенный CLI-контур `init/rotate/rewrap/delete/status/run-maintenance`, persisted managed env keyring, policy-driven auto-rotation, post-verify, manual password gate и вынос orchestration в `usecases/management/vault`.
- **Плюсы**: Закрывает полный lifecycle и снижает операционные риски.
- **Минусы**: Больше объём внедрения и тестирования.

### Вариант 4: Немедленный переход на внешний KMS/Transit
- **Идея**: Убрать локальный keyring lifecycle и делегировать ключи внешнему сервису.
- **Плюсы**: Enterprise security baseline.
- **Минусы**: Существенно увеличивает scope (auth, network reliability, ops).

---

## 🔗 Связанные документы

- [VAULT-DEC-001](./VAULT-DEC-001-envelope-encrypted-vault-with-hexagonal-ports.md)
- [VAULT-DEC-002](./VAULT-DEC-002-vault-management-managed-env-keyring-and-rotation-lifecycle.md)
- [vault-crypto.md](../../dev/layers/vault/vault-crypto.md)
- [vault-delivery.md](../../dev/layers/vault/vault-delivery.md)

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-03-04 | Проблема зафиксирована по итогам анализа vault lifecycle в production-эксплуатации |
| 2026-03-04 | Сформирован целевой вариант решения в [VAULT-DEC-002](./VAULT-DEC-002-vault-management-managed-env-keyring-and-rotation-lifecycle.md) |
| 2026-03-07 | Проблема закрыта: реализован полный lifecycle в рамках DEC-002 (CLI/usecase/startup-maintenance/test-matrix) |
