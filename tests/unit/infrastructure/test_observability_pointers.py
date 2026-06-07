"""Юнит-тесты stable-pointer публикации для observability-артефактов."""

from __future__ import annotations

from pathlib import Path

import pytest

from connector.common.observability import ObservabilityArtifactKind
from connector.infra.observability.pointers import LatestArtifactPointerPublisher

pytestmark = pytest.mark.unit


def test_pointer_publisher_creates_symlink_for_log_when_supported(
    tmp_path: Path,
) -> None:
    publisher = LatestArtifactPointerPublisher()
    log_path = tmp_path / "planner" / "2026-06-05_planner.log"
    log_path.parent.mkdir(parents=True)
    log_path.write_text("line-1\nline-2\n", encoding="utf-8")

    result = publisher.publish(
        artifact_kind=ObservabilityArtifactKind.LOG,
        artifact_path=log_path,
    )

    assert result is not None
    assert result.pointer_path.name == "current.log"
    assert result.pointer_path.exists()
    assert result.pointer_path.read_text(encoding="utf-8") == "line-1\nline-2\n"


def test_pointer_publisher_falls_back_to_copy_when_symlink_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    publisher = LatestArtifactPointerPublisher()
    report_path = tmp_path / "planner" / "2026-06-05T10-00-00_planner.json"
    report_path.parent.mkdir(parents=True)
    report_path.write_text('{"status":"SUCCESS"}', encoding="utf-8")

    def _raise_symlink(*_args, **_kwargs) -> None:
        raise OSError("symlink disabled")

    monkeypatch.setattr(Path, "symlink_to", _raise_symlink)

    result = publisher.publish(
        artifact_kind=ObservabilityArtifactKind.REPORT,
        artifact_path=report_path,
    )

    assert result is not None
    assert result.mode == "copy"
    assert result.pointer_path.name == "latest.json"
    assert result.pointer_path.read_text(encoding="utf-8") == '{"status":"SUCCESS"}'
