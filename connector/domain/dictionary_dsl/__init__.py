"""
Назначение:
    Public API Dictionary DSL layer: Pydantic specs и loader helpers.

Граница ответственности:
    - Экспортирует только domain-level модели/функции загрузки.
    - Не экспортирует infra/runtime реализации.
"""

from connector.domain.dictionary_dsl.loader import (
    load_dictionary_manifest_spec,
    load_dictionary_manifest_spec_for_registry,
    load_dictionary_manifest_spec_for_runtime,
    load_dictionary_registry_spec,
    load_dictionary_registry_spec_for_runtime,
    load_dictionary_spec,
    load_dictionary_spec_for_runtime,
    load_enabled_dictionary_specs_for_runtime,
    load_optional_dictionary_registry_spec_for_runtime,
)
from connector.domain.dictionary_dsl.specs import (
    DICTIONARY_NORMALIZED_KEY_OPS_WHITELIST,
    DictionaryLookupSpec,
    DictionaryManifestItemSpec,
    DictionaryManifestSpec,
    DictionaryNormalizedKeySpec,
    DictionaryRegistryItemSpec,
    DictionaryRegistrySpec,
    DictionarySchemaSpec,
    DictionarySourceCsvSpec,
    DictionarySourceSpec,
    DictionarySpec,
)

__all__ = [
    "DICTIONARY_NORMALIZED_KEY_OPS_WHITELIST",
    "DictionaryLookupSpec",
    "DictionaryManifestItemSpec",
    "DictionaryManifestSpec",
    "DictionaryNormalizedKeySpec",
    "DictionaryRegistryItemSpec",
    "DictionaryRegistrySpec",
    "DictionarySchemaSpec",
    "DictionarySourceCsvSpec",
    "DictionarySourceSpec",
    "DictionarySpec",
    "load_dictionary_manifest_spec",
    "load_dictionary_manifest_spec_for_registry",
    "load_dictionary_manifest_spec_for_runtime",
    "load_dictionary_registry_spec",
    "load_dictionary_registry_spec_for_runtime",
    "load_dictionary_spec",
    "load_dictionary_spec_for_runtime",
    "load_enabled_dictionary_specs_for_runtime",
    "load_optional_dictionary_registry_spec_for_runtime",
]
