"""
Централизованные коды ошибок приложения.

Назначение/ответственность:
    Содержит единый набор строковых кодов, используемых во всех слоях
    (use-case, отчёты, infra-адаптеры) для унификации сообщений и логов.
Инварианты/гарантии:
    - Коды стабильны и задаются как константы.
    - Новые коды добавляются здесь, а не "на лету" в разных модулях.
Взаимодействия:
    - ExecutionResult.error_code должен ссылаться на значения отсюда.
    - ApiError.code (если проброшен из infra) маппится в один из этих кодов.
Ограничения:
    - Строковые значения остаются человекочитаемыми для логов/отчётов.
"""

class ErrorCode:
    # Сетевые/транспортные ошибки
    HTTP_TIMEOUT = "HTTP_TIMEOUT"
    HTTP_CONNECTION = "HTTP_CONNECTION"
    HTTP_4XX = "HTTP_4XX"
    HTTP_5XX = "HTTP_5XX"
    HTTP_UNEXPECTED_STATUS = "HTTP_UNEXPECTED_STATUS"
    NETWORK_ERROR = "NETWORK_ERROR"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"

    # Ошибки формата/контента
    INVALID_JSON = "INVALID_JSON"

    # Прикладные/ограничения API
    MAX_PAGES_EXCEEDED = "MAX_PAGES_EXCEEDED"
    API_CONFLICT = "API_CONFLICT"
    API_VALIDATION = "API_VALIDATION"


__all__ = ["ErrorCode"]
