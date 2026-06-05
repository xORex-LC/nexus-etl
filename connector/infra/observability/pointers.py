"""Latest artifact pointers — публикация удобных ссылок на свежие observability-файлы.

Модуль обновляет `current.log` и `latest.json` рядом с реальными
observability-артефактами. Основной режим — симлинк на свежий файл; если
симлинки недоступны или запрещены окружением, используется fallback на копию.

Границы ответственности:
    - Публиковать стабильные указатели на последние log/report/plan артефакты.
    - Делать symlink->copy fallback без влияния на основной runtime path.

Вне ответственности:
    - Поиск последнего артефакта через ledger.
    - CLI rendering и чтение содержимого артефактов.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from connector.common.observability import ObservabilityArtifactKind


@dataclass(frozen=True)
class PointerPublishResult:
    """Итог публикации одного stable-pointer файла."""

    pointer_path: Path
    mode: str


class LatestArtifactPointerPublisher:
    """Обновлять `current.log` / `latest.json` рядом с observability-артефактами."""

    def publish(
        self,
        *,
        artifact_kind: ObservabilityArtifactKind,
        artifact_path: str | Path | None,
    ) -> PointerPublishResult | None:
        """Опубликовать stable pointer для уже созданного артефакта.

        Args:
            artifact_kind: Тип артефакта, определяющий имя указателя.
            artifact_path: Путь к реально созданному файлу. `None` приводит к no-op.

        Returns:
            Информацию о созданном указателе или `None`, если публиковать нечего.
        """
        if artifact_path is None:
            return None

        source_path = Path(artifact_path)
        if not source_path.exists() or not source_path.is_file():
            return None

        pointer_path = source_path.parent / _pointer_name_for(artifact_kind)
        if pointer_path.exists() or pointer_path.is_symlink():
            pointer_path.unlink()

        try:
            pointer_path.symlink_to(source_path.name)
            return PointerPublishResult(pointer_path=pointer_path, mode="symlink")
        except OSError:
            shutil.copy2(source_path, pointer_path)
            return PointerPublishResult(pointer_path=pointer_path, mode="copy")


def _pointer_name_for(artifact_kind: ObservabilityArtifactKind) -> str:
    if artifact_kind == ObservabilityArtifactKind.LOG:
        return "current.log"
    return "latest.json"


__all__ = ["LatestArtifactPointerPublisher", "PointerPublishResult"]
