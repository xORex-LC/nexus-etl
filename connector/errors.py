from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class AppError(Exception):
    """
    Унифицированная ошибка приложения.
    """

    category: str
    code: str
    message: str
    retryable: bool = False
    details: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        super().__init__(self.message)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category,
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "details": self.details or {},
        }


__all__ = ["AppError"]
