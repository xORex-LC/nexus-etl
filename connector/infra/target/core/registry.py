"""Реестр target-провайдеров и выбор провайдера по target_type."""

from __future__ import annotations

from connector.infra.target.core.provider import TargetProvider


class MissingTargetProviderError(LookupError):
    """Исключение при отсутствии запрошенного target-провайдера в реестре."""


class TargetProviderRegistry:
    """Ручной реестр target-провайдеров.

    Хранит соответствие ``target_type -> TargetProvider`` и поддерживает
    выбор провайдера по умолчанию.
    """

    def __init__(self) -> None:
        self._providers: dict[str, TargetProvider] = {}
        self._default_target_type: str | None = None

    def register(self, provider: TargetProvider, *, default: bool = False) -> None:
        """Зарегистрировать provider в реестре.

        Raises:
            ValueError: если provider с таким target_type уже зарегистрирован.
        """
        target_type = provider.target_type
        if target_type in self._providers:
            raise ValueError(f"Target provider already registered: {target_type}")
        self._providers[target_type] = provider
        if default or self._default_target_type is None:
            self._default_target_type = target_type

    def get(self, target_type: str) -> TargetProvider:
        """Получить provider по target_type.

        Raises:
            MissingTargetProviderError: если provider не найден.
        """
        provider = self._providers.get(target_type)
        if provider is None:
            known = ", ".join(sorted(self._providers)) or "<none>"
            raise MissingTargetProviderError(
                f"Target provider '{target_type}' is not registered. Known providers: {known}",
            )
        return provider

    def get_default(self) -> TargetProvider:
        """Получить provider, помеченный как default.

        Raises:
            MissingTargetProviderError: если default provider не задан.
        """
        if self._default_target_type is None:
            raise MissingTargetProviderError("No default target provider is registered")
        return self.get(self._default_target_type)
