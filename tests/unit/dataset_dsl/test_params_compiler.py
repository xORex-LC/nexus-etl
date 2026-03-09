"""Tests for params_compiler."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from connector.domain.dataset_dsl.params_compiler import (
    build_target_id_params,
    resolve_params_builder,
)
from connector.domain.dataset_dsl.specs import ParamsSpec


class TestBuildTargetIdParams:
    def test_valid(self):
        item = MagicMock()
        item.target_id = "42"
        assert build_target_id_params(item) == {"target_id": "42"}

    def test_strips_whitespace(self):
        item = MagicMock()
        item.target_id = "  42  "
        assert build_target_id_params(item) == {"target_id": "42"}

    def test_none_raises(self):
        item = MagicMock()
        item.target_id = None
        with pytest.raises(ValueError, match="target_id is required"):
            build_target_id_params(item)

    def test_empty_raises(self):
        item = MagicMock()
        item.target_id = "   "
        with pytest.raises(ValueError, match="target_id is required"):
            build_target_id_params(item)

    def test_numeric_target_id(self):
        item = MagicMock()
        item.target_id = 123
        assert build_target_id_params(item) == {"target_id": "123"}


class TestResolveParamsBuilder:
    def test_target_id_mode(self):
        spec = ParamsSpec(mode="target_id")
        builder = resolve_params_builder(spec)
        assert builder is build_target_id_params

    def test_none_mode(self):
        spec = ParamsSpec(mode="none")
        builder = resolve_params_builder(spec)
        assert builder is None
