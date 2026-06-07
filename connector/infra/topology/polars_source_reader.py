"""Polars source adjacency reader — source projection для Stage G.

Адаптер читает физический CSV source и проецирует его в domain DTO
`SourceAdjacencyNode`. Он знает только имена source-колонок из topology/source
spec и параметры CSV, но не принимает anchoring decisions.

Зона ответственности:
    - Читать source CSV через Polars
    - Нормализовать пустые parent_id в None
    - Отдать deterministic source adjacency projection

Вне области ответственности:
    - Anchoring/reachability и duplicate policy
    - Row-level diagnostics и report emission
    - Cache/target membership access
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import polars as pl

from connector.domain.dependency_tree import SourceAdjacencyNode
from connector.domain.ports.topology import SourceAdjacencyReadPort


class PolarsSourceAdjacencyReader(SourceAdjacencyReadPort):
    """Прочитать source adjacency list из CSV source-файла."""

    def __init__(
        self,
        *,
        path: str | Path,
        has_header: bool,
        delimiter: str,
        encoding: str,
        node_id_field: str,
        parent_id_field: str,
        label_field: str,
    ) -> None:
        self._path = str(Path(path))
        self._has_header = has_header
        self._delimiter = delimiter
        self._encoding = encoding
        self._node_id_field = node_id_field
        self._parent_id_field = parent_id_field
        self._label_field = label_field

    def read_nodes(self) -> Iterable[SourceAdjacencyNode]:
        frame = pl.read_csv(
            self._path,
            has_header=self._has_header,
            separator=self._delimiter,
            encoding=self._encoding,
            infer_schema_length=0,
            null_values=["", "null", "NULL"],
        )
        required = {
            self._node_id_field,
            self._parent_id_field,
            self._label_field,
        }
        missing = sorted(required.difference(frame.columns))
        if missing:
            raise ValueError(
                "source topology adjacency columns are missing: "
                + ", ".join(missing)
            )
        projected = (
            frame.select(
                pl.col(self._node_id_field).cast(pl.Utf8).str.strip_chars().alias("node_id"),
                pl.col(self._parent_id_field)
                .cast(pl.Utf8)
                .str.strip_chars()
                .alias("parent_id"),
                pl.col(self._label_field).cast(pl.Utf8).str.strip_chars().alias("label"),
            )
            .filter(pl.col("node_id").is_not_null() & (pl.col("node_id") != ""))
            .unique(maintain_order=True)
        )
        for row in projected.iter_rows(named=True):
            yield SourceAdjacencyNode(
                node_id=str(row["node_id"]),
                parent_id=_optional_str(row["parent_id"]),
                label=str(row["label"] or ""),
            )


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized:
        return None
    return normalized
