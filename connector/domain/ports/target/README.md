# connector/domain/ports/target

## Назначение

Интерфейсы взаимодействия с целевой системой (REST API).

## Порты

| Файл | Порт | Назначение |
|---|---|---|
| `execution.py` | `RequestExecutorProtocol` | Выполнение подготовленного `RequestSpec` → `ExecutionResult` |
| `execution.py` | `RequestSpec`, `ExecutionResult` | DTO запроса и результата |
| `apply.py` | `ApplyAdapterProtocol` | Преобразование `PlanItem` → `RequestSpec` (гидрация payload, секретов) |
| `read.py` | `TargetPagedReaderProtocol` | Постраничное чтение данных из target (`iter_pages()`) — для cache refresh |

## Реализация

→ `infra/target/` (`TargetGateway`, `OperationApplyAdapter`)
