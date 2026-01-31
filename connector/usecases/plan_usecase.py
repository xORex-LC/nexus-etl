from __future__ import annotations

from dataclasses import dataclass

from connector.domain.planning.plan_builder import PlanBuilder, PlanBuildResult
from connector.domain.planning.match_models import ResolveOp

@dataclass
class PlanUseCase:
    """
    Назначение/ответственность:
        Use-case планирования импорта: принимает resolved строки и собирает итог через PlanBuilder.

    Взаимодействия:
        - Не знает об артефактах/файлах и не хранит планы в памяти.

    Ограничения:
        Синхронное выполнение; источники строк и зависимости передаются извне.
    """

    def __init__(
        self,
    ) -> None:
        pass

    def run(
        self,
        resolved_row_source,
    ) -> PlanBuildResult:
        """
        Контракт (вход/выход):
            Вход: resolved_row_source (Iterable[TransformResult[ResolvedRow]]).
            Выход: PlanBuildResult (items, summary).
        Ошибки/исключения:
            Пробрасывает CsvFormatError/OSError и исключения зависимостей.
        Алгоритм:
            - Проходит resolved строки и собирает план.
            - Возвращает результат builder.build().
        """
        builder = PlanBuilder()

        for resolved in resolved_row_source:
            resolved_row = resolved.row
            if resolved_row is None:
                continue
            if resolved.errors:
                continue
            if resolved_row.op == ResolveOp.CONFLICT:
                continue
            builder.add_resolved(resolved_row)

        return builder.build()
