# TRANSFORM-PROBLEM-002: TransformProviderDeps coupling — обязательный cache_gateway нарушает pay-for-what-you-use

> **Статус**: Открыта — митигация применена (Вариант A); подпроблема корневой [TRANSFORM-PROBLEM-004](./TRANSFORM-PROBLEM-004-missing-modular-pipeline-architecture.md); целевое решение: [TRANSFORM-DEC-004](./TRANSFORM-DEC-004-modular-pipeline-scoped-execution-context.md) (поглотило DEC-002)
> **Дата создания**: 2026-02-20
> **Затронутые компоненты**: `TransformProviderDeps`, `connector/domain/transform/providers/deps.py`

---

## 📋 Контекст

`TransformProviderDeps` — это контейнер runtime-зависимостей для enrich stage. Он передаётся в `EnricherEngine` и используется provider-функциями для получения внешних ресурсов (cache, dictionary, secrets).

На момент создания enrich поддерживал только один тип lookup-провайдера: `cache.by_field`. Поэтому `cache_gateway` был объявлен обязательным полем — единственным внешним ресурсом.

С добавлением Dictionary Layer появились use-cases, в которых `cache.by_field` не используется вообще: enrich-правила обращаются только к `dictionary.by_key`. Это обнажило архитектурный изъян в дизайне `TransformProviderDeps`.

---

## ⚠️ Проблема

`cache_gateway: EnrichLookupPort` объявлен без default — конструктор требует его явно:

```python
@dataclass(frozen=True)
class TransformProviderDeps:
    cache_gateway: EnrichLookupPort          # обязателен, нет default
    secret_store: SecretStoreProtocol | None = None
    dictionaries: DictionaryProviderPort | None = None
```

Это значит: любой `DatasetSpec`, реализующий `build_enrich_deps()`, обязан получить и передать реализацию `EnrichLookupPort` — даже если ни одно enrich-правило не обращается к `cache.by_field` или `cache.exists_by_field`.

По мере добавления новых capabilities (`dictionaries`, в будущем telemetry, external API, feature flags) `TransformProviderDeps` будет расти как flat catch-all без механизма, позволяющего декларировать "этот dataset использует только вот это".

---

## 🔍 Симптомы

- **Симптом 1**: Dataset, в enrich-правилах которого нет ни одного `cache.*` провайдера, обязан получить `SqliteCacheGateway` и передать его в deps — coupling к SQL-инфраструктуре без реальной нужды.
- **Симптом 2**: Нет type-safe способа объявить "только dictionary" — все поля кроме `cache_gateway` опциональны, но `cache_gateway` обязателен вне зависимости от реального профиля.
- **Симптом 3**: Provider-функции (`_cache_by_field`, `_cache_exists_by_field`) уже используют `getattr(deps, "cache_gateway", None)` с runtime-guard, т.е. реально `cache_gateway` нужен только если вызывается — но тип системы этого не отражает.
- **Симптом 4**: `TransformProviderDeps` не имеет механизма проверки "хватает ли у меня зависимостей для этого набора enrich-правил" на этапе сборки pipeline.

---

## 📊 Масштаб проблемы

- **Частота**: Латентная — проявляется при добавлении dataset specs с нестандартными capability-профилями
- **Критичность**: Средняя — не блокирует работу, но создаёт coupling и ограничивает расширяемость
- **Затронуто**: Все будущие `DatasetSpec`-реализации, которые используют только часть capabilities enrich

---

## 🧪 Как воспроизвести

1. Создать новый `DatasetSpec`, в котором все enrich-правила используют только `dictionary.by_key`
2. Реализовать `build_enrich_deps()` — попытаться не передавать `cache_gateway`
3. **Ожидаемый результат**: допустимо, `cache_gateway` не нужен этому spec
4. **Фактический результат** (до митигации): `TypeError: __init__() missing 1 required positional argument: 'cache_gateway'`

---

## 🚫 Почему это проблема?

- Нарушается принцип "pay for what you use" — обязательная зависимость к SQL-инфраструктуре при её реальной незадействованности
- Усложняет тестирование: тест dictionary-only spec обязан поднимать SqliteCacheGateway
- `TransformProviderDeps` превращается в flat catch-all, который будет расти с каждой новой capability
- Нет декларативного способа сообщить "этот stage требует вот эти порты" — capability-профиль неявен

---

## 💡 Возможные решения (обсуждение)

### Вариант A: Сделать все поля опциональными

- **Идея**: `cache_gateway: EnrichLookupPort | None = None` — убрать required
- **Плюсы**: Минимальный изменение, мгновенный эффект, код не меняется
- **Минусы**: Симптом устранён, корневая проблема нет — dataclass по-прежнему catch-all без capability-семантики

### Вариант B: Protocol structural split

- **Идея**: Отдельные `HasCacheGateway`, `HasDictionaries` Protocol для структурной типизации
- **Плюсы**: Явные capability-требования на уровне типов
- **Минусы**: Python Protocol runtime-checking громоздкий; нет реального выигрыша над Вариантом A при текущем масштабе

### Вариант C: TransformContext — typed capability registry

- **Идея**: Заменить dataclass на typed service locator, индексированный по типу порта: `ctx.require(EnrichLookupPort)`, `ctx.get(DictionaryProviderPort)`
- **Плюсы**: Истинный "pay for what you use", open/closed, масштабируется на любое количество capabilities
- **Минусы**: Высокая стоимость рефактора; `ctx.require(SomePort)` слабее IDE autocomplete; оправдан только при 5+ capabilities или 3+ dataset specs с разными профилями

---

## 🔗 Связанные документы

- [TRANSFORM-DEC-002](./TRANSFORM-DEC-002-transform-context-capability-registry.md) — принятое целевое решение (Вариант C) + митигация (Вариант A)
- `connector/domain/transform/providers/deps.py` — затронутый файл
- `connector/domain/transform/providers/registry.py` — provider-функции с `getattr`-guard

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-02-20 | Проблема обнаружена при добавлении Dictionary Layer |
| 2026-02-20 | Митигация Вариант A применена: `cache_gateway: EnrichLookupPort \| None = None` |
| 2026-02-20 | Целевое решение зафиксировано в TRANSFORM-DEC-002 (Вариант C — TransformContext) |
| 2026-02-20 | `PendingSettings` удалён, `AppSettings.resolver: ResolverSettings` — домен-тип напрямую как app-settings слайс; `_build_resolver_settings()` удалён; блокер для TRANSFORM-DEC-002 устранён |
| 2026-02-22 | Идентифицирована как подпроблема корневой TRANSFORM-PROBLEM-004; целевое решение DEC-002 поглощено DEC-004 |
