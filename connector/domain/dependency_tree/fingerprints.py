"""Хелперы fingerprint-ов dependency_tree — детерминированные topology-хэши

Предоставляет stable SHA-256 helpers для source-side synthetic identifiers и
topology structural signatures. Функции этого модуля намеренно не используют
Python `hash()`, потому что его вывод process-randomized и непригоден для
reproducible ETL artefacts.

Зона ответственности:
    - Строить deterministic source synthetic ids из canonical paths
    - Строить deterministic structural signatures для query-time comparisons

Вне области ответственности:
    - Node ingestion или graph validation
    - Runtime metadata/provenance containers
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def build_source_synthetic_id(
    canonical_segments: tuple[str, ...],
    *,
    normalization_version: str,
) -> str:
    """Построить детерминированный source-side node id для canonical path prefix

    Параметры:
        canonical_segments: Canonical path prefix как ordered segments.
        normalization_version: Версия canonicalization contract, зашитая в ids.

    Возвращает:
        Stable SHA-256 hex digest для пары path/version.
    """

    return _stable_sha256(
        {
            "kind": "source_topology_node",
            "normalization_version": normalization_version,
            "canonical_segments": list(canonical_segments),
        }
    )


def build_structural_signature(
    *,
    canonical_path: tuple[str, ...],
    root_id: str,
    depth: int,
) -> str:
    """Построить детерминированную signature для structural position узла"""

    return _stable_sha256(
        {
            "kind": "topology_structural_signature",
            "canonical_path": list(canonical_path),
            "root_id": root_id,
            "depth": depth,
        }
    )


def _stable_sha256(payload: Any) -> str:
    serialized = json.dumps(
        payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
