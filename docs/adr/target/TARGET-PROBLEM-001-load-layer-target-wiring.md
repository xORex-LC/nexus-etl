# TARGET-PROBLEM-001: Нечистая граница load-слоя (apply/refresh/check) и зависимость CLI wiring от конкретного target

> **Статус**: Решена в [TARGET-DEC-001](./TARGET-DEC-001-target-runtime-target-spec-slice.md), уточнена в [TARGET-DEC-003](./TARGET-DEC-003-target-core.md)  
> **Дата создания**: 2026-02-13  
> **Затронутые компоненты**: `connector/delivery/cli/bootstrap.py`, `connector/delivery/commands/import_apply.py`, `connector/delivery/commands/cache_refresh.py`, `connector/delivery/commands/check_api.py`, `connector/infra/http/ankey_client.py`, `connector/infra/http/request_executor.py`, `connector/infra/target/ankey_gateway.py`

---

## 📋 Контекст

После завершения миграции cache DSL и консолидации DSL/runtime слой `load` (в терминах проекта: применение плана `apply` и связанные операции чтения target для `cache refresh`, плюс `check_api`) остался фактически “как было с начала разработки”:

- CLI wiring собирает target-инфраструктуру напрямую (HTTP клиент, executor, reader).
- Команды (`import_apply`, `cache_refresh`, `check_api`) знают конкретный target (`Ankey`), его базовый URL и часть политики ретраев/параметров.
- Use-case слой уже в целом опирается на порты (`RequestExecutorProtocol`, `TargetPagedReaderProtocol`), но сборка реализаций этих портов не выделена в отдельный target slice и размазана по CLI bootstrap/командам.

Сейчас мы планируем заняться `plan/import/target/infra (sink)` и хотим:
- зафиксировать корректный контракт между `apply` и `target`, чтобы `apply` не зависел от типа infra;
- вынести всю API/target специфику в Infra и перестать собирать клиентов “вручную” в `delivery/cli/bootstrap.py`.

---

## ⚠️ Проблема

**Суть**: слой `delivery` (CLI runtime и команды) напрямую зависит от конкретной target-инфраструктуры и повторяет wiring/параметры подключения, из-за чего:

- нарушается Clean/Hex граница (delivery тянет конкретные infra-реализации и даже infra-исключения);
- повторяется код сборки клиента/исполнителя/ридера и формирования мета-контекста target;
- добавление нового типа target (db/rest/file/другой api) неизбежно приведёт к правкам в нескольких командах и bootstrap, а также к усложнению тестирования.

**Где это видно в коде (AS-IS):**
- `connector/delivery/cli/bootstrap.py` импортирует и создаёт `AnkeyApiClient`, `AnkeyRequestExecutor`, `AnkeyTargetPagedReader`.
- `connector/delivery/commands/import_apply.py` создаёт `client/executor` через bootstrap-функции и формирует контекст target (base_url, user, retry параметры).
- `connector/delivery/commands/cache_refresh.py` повторяет тот же подход (client/reader/base_url) и дополнительно прокидывает transport.
- `connector/delivery/commands/check_api.py` напрямую использует `ApiError` из `connector.infra.http.ankey_client`.

---

## 🔍 Симптомы

- **Дублирование wiring к target**:
  - повторяются `build_api_client/build_api_executor/build_api_reader` и связанный контекст (`base_url`, retries, backoff) в разных командах.
- **Сцепление delivery ↔ infra**:
  - команды вынуждены знать про `AnkeyApiClient`/`ApiError`/специфику эндпоинтов `"/ankey/managed/user"`.
- **Сложность поддержки нескольких target-типов**:
  - чтобы добавить второй target, придётся либо ветвить `bootstrap.py`, либо ветвить каждую команду.
- **Хрупкие тесты / сложный monkeypatch**:
  - тестам приходится патчить конкретные импорты/фабрики, и небольшая перестановка wiring ломает E2E (типичный симптом неправильной точки инъекции зависимостей).
- **Неявное размазывание “политики подключения”**:
  - timeout/retry/backoff и transport прокидываются на уровне команд, а не управляются единым target runtime.

---

## 📊 Масштаб проблемы

- **Частота**: Всегда (каждый запуск apply/refresh/check проходит через этот wiring)
- **Критичность**: Средняя → Высокая (архитектурный блокер для развития target слоя и поддержки нескольких типов sink)
- **Затронуто**:
  - Use cases: `ImportApplyService`, `CacheRefreshUseCase` (косвенно через wiring)
  - CLI команды: `import_apply`, `cache_refresh`, `check_api`
  - Тестирование: e2e/интеграционные тесты вокруг команд и target клиента

---

## 🧪 Как воспроизвести

1. Открыть `connector/delivery/cli/bootstrap.py` и увидеть прямые импорты target-инфры:
   - `from connector.infra.http.ankey_client import AnkeyApiClient`
   - `from connector.infra.http.request_executor import AnkeyRequestExecutor`
   - `from connector.infra.target.ankey_gateway import AnkeyTargetPagedReader`

2. Найти повторяющиеся места сборки target-клиента/контекста в командах:
   ```bash
   grep -R "build_api_client\|build_api_reader\|build_api_executor\|base_url = f\"https" -n connector/delivery/commands
   ```

3. Смоделировать добавление второго target (например, другой REST API):
   - потребуется добавлять новые функции вида `build_other_api_client`, `build_other_executor`, `build_other_reader`
   - затем менять `import_apply.py`, `cache_refresh.py`, `check_api.py` чтобы ветвиться по типу target

4. **Ожидаемый результат**:  
   Команды получают готовые порты target-слоя из единой фабрики/runtime (не знают конкретную infra), а смена target меняется конфигом и/или выбором реализации фабрики.

5. **Фактический результат**:  
   Команды и bootstrap жёстко прошивают Ankey и требуют правок в нескольких местах при любом расширении target-слоя.

---

## 🚫 Почему это проблема?

- **Нарушение Clean/Hex**: delivery слой начинает “знать” конкретную инфраструктуру и её исключения/особенности.
- **Плохая расширяемость**: добавление новых target типов не локализуется; растёт количество ветвлений и копипасты.
- **Сложнее тестировать**: патчинг зависит от места импорта; небольшие рефакторы wiring ломают тесты.
- **Риск рассинхронизации поведения**: разные команды могут случайно расходиться в параметрах подключения/ретраев/таймаутов.
- **Тормозит дальнейшую работу по sink**: пока не оформлен target slice и единый контракт сборки, любые изменения в API/target будут пачкать delivery и усложнять сопровождение.

---

## 💡 Возможные решения (обсуждение)

### Вариант 1: Оставить как есть (минимальные правки точечно)
- **Идея**: продолжать собирать клиентов в `bootstrap.py`, а команды — напрямую использовать `build_api_*`.
- **Плюсы**:
  - нулевая стоимость сейчас
- **Минусы**:
  - проблема расширяемости и Clean/Hex остаётся
  - повторение wiring продолжит расти
  - второй target приведёт к комбинаторике ветвлений

### Вариант 2: Ввести TargetRuntime/TargetFactory в infra и выдавать порты (рекомендуемый старт)
- **Идея**: выделить единый “target slice” в `connector/infra/target_runtime/*`, который по настройкам возвращает:
  - `RequestExecutorProtocol` (для apply)
  - `TargetPagedReaderProtocol` (для refresh)
  - (опционально) `healthcheck`/`capabilities`
- **Плюсы**:
  - команды перестают знать про `Ankey*` классы
  - единая точка управления политиками подключения (retry/backoff/timeout/transport)
  - тестам проще: патчим фабрику/рантайм, а не конкретные импорты
- **Минусы**:
  - нужно аккуратно определить минимальный контракт TargetRuntime, чтобы не раздувать абстракции

### Вариант 3: Добавить декларативный TargetSpec (YAML) как источник для TargetFactory
- **Идея**: описывать тип target и параметры подключения в отдельном `target.yaml` (или slice в settings), а фабрика строит runtime из этого описания.
- **Плюсы**:
  - конфигурация target становится явной и переносимой
  - проще подключать разные target без правок кода
- **Минусы**:
  - если начать “слишком широко” (db/file/rest сразу), можно уйти в оверинжиниринг
  - всё равно нужен Variant 2 (фабрика/рантайм), YAML — лишь источник данных

### Вариант 4: Полноценный DI/Resources контейнер на весь runtime
- **Идея**: общий контейнер зависимостей (api/cache/secrets/datasets/observability/target) и инъекция во все команды.
- **Плюсы**:
  - максимально единообразный runtime wiring
- **Минусы**:
  - высокий риск оверинжиниринга сейчас (можно прийти к “мини-фреймворку”)
  - для нашей задачи target-cleanup достаточно Variant 2 (+ возможно Variant 3)

---

## 🔗 Связанные документы

- [ADR INDEX](../INDEX.md) — реестр ADR и соглашения по именованию
- [CONFIG-DEC-001](../config/CONFIG-DEC-001-modular-settings-and-slice-wiring.md) — текущий подход к modular settings/wiring
- [CLI settings layer](../../dev/layers/config/cli-settings-layer.md) — как устроен слой настроек
- `connector/delivery/cli/bootstrap.py` — текущая сборка target-инфры (проблемная зона)
- `connector/domain/ports/target/*` — target-порты (`RequestExecutorProtocol`, `TargetPagedReaderProtocol`)
- [TEMPLATE-PROBLEM.md](../TEMPLATE-PROBLEM.md) — шаблон документа

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-02-13 | Зафиксирована проблема: target wiring и target специфика размазаны по CLI bootstrap и командам |
| 2026-02-13 | Принято начать с “чистоты load-слоя” (оформить target slice и единый контракт сборки портов) |
| 2026-02-13 | Принято решение [TARGET-DEC-001](./TARGET-DEC-001-target-runtime-target-spec-slice.md) |
| 2026-02-16 | Консолидировано и расширено решением [TARGET-DEC-003](./TARGET-DEC-003-target-core.md) |
