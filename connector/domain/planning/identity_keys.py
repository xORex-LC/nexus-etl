from __future__ import annotations


def format_identity_key(name: str, value: str) -> str:
    """
    Назначение:
        Унифицированное представление ключа для identity_index.
    """
    return f"{name}:{value}"
