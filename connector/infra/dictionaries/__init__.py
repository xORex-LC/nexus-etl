"""
Назначение:
    Infra runtime компоненты Dictionary layer (v1 foundation).

Граница ответственности:
    - Содержит runtime compilation, CSV loading и backend реализации.
    - Не содержит DI/container wiring (delivery слой).
"""

from connector.infra.dictionaries.dsl_runtime import (
    CompiledDictionaryOperation,
    CompiledDictionarySpec,
    DictionaryDslRuntimeBundle,
    build_dictionary_dsl_runtime,
)
from connector.infra.dictionaries.loader_csv import CsvDictionaryLoader
from connector.infra.dictionaries.versioning import (
    DictionaryVersionInfo,
    build_content_sha256_bytes,
    build_content_sha256_for_file,
    build_dictionary_schema_hash,
    build_dictionary_version_id,
    build_dictionary_version_info,
)

__all__ = [
    "CompiledDictionaryOperation",
    "CompiledDictionarySpec",
    "CsvDictionaryLoader",
    "DictionaryDslRuntimeBundle",
    "DictionaryVersionInfo",
    "build_content_sha256_bytes",
    "build_content_sha256_for_file",
    "build_dictionary_dsl_runtime",
    "build_dictionary_schema_hash",
    "build_dictionary_version_id",
    "build_dictionary_version_info",
]

