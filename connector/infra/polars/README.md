# connector/infra/polars

## Назначение

Infra-level Polars adapters для vectorized исполнения shared runtime-контрактов.
Пакет замыкает на `polars` те domain-объекты, которые специально оставлены
transport-neutral в `domain/transform/common/`.

## Файлы

| Файл | Назначение |
|---|---|
| `canonicalization.py` | Реальный Polars adapter для `CompiledPolarsExpressionPlan`: строит `pl.Expr` для canonicalization list/scalar path-ов |

## Зависимости

**Зависит от:** `domain/transform/common/`, `polars`.  
**Используется:** topology/cache consumers, которым нужен vectorized canonicalization path.
