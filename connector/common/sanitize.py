def maskSecret(value: str | None) -> str | None:
    """
    Назначение:
        Маскирует секреты для безопасного вывода в stdout/logs.

    Входные данные:
        value: str | None
            Исходное значение (например, пароль).

    Выходные данные:
        str | None
            Если value задано — возвращает '***', иначе None.

    Алгоритм:
        - Если значение отсутствует, вернуть None.
        - Иначе вернуть фиксированную маску '***'.
    """
    if value is None:
        return None
    return "***"


def isMaskedSecret(value: str | None) -> bool:
    """
    Проверяет, является ли значение замаскированным секретом.

    Возвращает True, если значение равно маске '***'.
    """
    return value == "***"


def truncateText(value: str | None, max_length: int = 500) -> str | None:
    """
    Назначение:
        Безопасно усечь строку для логирования/отчётов.

    Контракт:
        - None возвращается как None.
        - Строки короче max_length возвращаются без изменений.
        - Длинные строки обрезаются и дополняются '...'.
    """
    if value is None:
        return None
    if len(value) <= max_length:
        return value
    return value[: max_length - 3] + "..."


def maskSecretsInObject(value, secret_keys: tuple[str, ...] = ("password", "token", "authorization")):
    """
    Назначение:
        Рекурсивно маскировать секреты в словарях/списках для безопасного вывода.
    """
    if isinstance(value, dict):
        masked = {}
        for k, v in value.items():
            if isinstance(k, str) and k.lower() in secret_keys:
                masked[k] = "***"
            else:
                masked[k] = maskSecretsInObject(v, secret_keys)
        return masked
    if isinstance(value, list):
        return [maskSecretsInObject(v, secret_keys) for v in value]
    return value


def truncateText(value: str | None, limit: int = 2000) -> str | None:
    """
    Назначение:
        Ограничивает длину текста, чтобы избежать раздувания логов/отчётов.

    Входные данные:
        value: str | None
            Текст для усечения.
        limit: int
            Максимально допустимая длина строки.

    Выходные данные:
        str | None
            Строка, не длиннее limit символов; None, если вход None.
    """
    if value is None:
        return None
    if len(value) <= limit:
        return value
    return value[:limit]


def maskSecretsInObject(
    obj: object,
    sensitive_keys: tuple[str, ...] = (
        "password",
        "token",
        "authorization",
        "api_key",
        "secret",
    ),
) -> object:
    """
    Назначение:
        Рекурсивно маскирует значения по заданным ключам в структурах dict/list.

    Входные данные:
        obj: object
            Любой объект (dict/list/примитив), потенциально содержащий секреты.
        sensitive_keys: tuple[str, ...]
            Ключи, значения которых следует маскировать.

    Выходные данные:
        object
            Новая структура с замаскированными секретами.
    """
    if isinstance(obj, dict):
        masked: dict[str, object] = {}
        for k, v in obj.items():
            if k.lower() in (key.lower() for key in sensitive_keys):
                masked[k] = maskSecret(str(v) if v is not None else None)
            else:
                masked[k] = maskSecretsInObject(v, sensitive_keys)
        return masked
    if isinstance(obj, list):
        return [maskSecretsInObject(item, sensitive_keys) for item in obj]
    return obj
