"""HTTP-модели операций транспорта."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class HttpOperationDataModel(BaseModel):
    """Транспортное описание HTTP-операции."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )

    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    path_template: str
    query_defaults: dict[str, Any] = Field(default_factory=dict)
    header_defaults: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_path_template(self) -> "HttpOperationDataModel":
        if not self.path_template.startswith("/"):
            raise ValueError("path_template must start with '/'")
        return self


__all__ = ["HttpOperationDataModel"]
