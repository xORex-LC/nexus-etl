"""Порты входа и справочников для transform-слоя."""

from connector.domain.ports.transform.sources import RowSource, SourceMapper
from connector.domain.ports.transform.dictionaries import DictionaryProviderPort

__all__ = [
    "RowSource",
    "SourceMapper",
    "DictionaryProviderPort",
]
