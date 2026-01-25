from __future__ import annotations

from connector.domain.models import ValidationRowResult
from connector.domain.planning.plan_models import Operation, PlanItem
from connector.domain.planning.plan_builder import PlanBuilder
from connector.domain.planning.protocols import PlanDecision, PlanDecisionKind, PlanningPolicyProtocol


class GenericPlanner:
    """
    Назначение/ответственность:
        Унифицированный доменный алгоритм планирования.
    Взаимодействия:
        Работает с PlanningPolicyProtocol и PlanBuilder; не знает о датасетах/IO.
    Ограничения:
        Не выполняет валидацию; принимает уже валидированные данные.
    """

    def __init__(self, policy: PlanningPolicyProtocol, builder: PlanBuilder) -> None:
        self._policy = policy
        self._builder = builder

    def plan_validated_row(
        self,
        validated_entity,
        validation: ValidationRowResult,
        warnings: list,
    ) -> None:
        """
        Назначение:
            Применить policy к валидированной строке и обновить PlanBuilder.
        Контракт (вход/выход):
            - Вход: validated_entity, ValidationRowResult, warnings (row+dataset).
            - Выход: None (эффект в builder).
        Ошибки/исключения:
            Пробрасывает только фатальные ошибки policy (invalid input/schema).
        Алгоритм:
            - policy.decide -> PlanDecision
            - create/update -> PlanItem -> builder.add_plan_item
            - skip/conflict -> builder.add_skip/add_conflict
        """
        decision: PlanDecision = self._policy.decide(validated_entity, validation)
        combined_warnings = list(warnings) + list(decision.warnings)
        identity_value = decision.identity.primary_value

        if decision.kind == PlanDecisionKind.CONFLICT:
            self._builder.add_conflict(validation.line_no, identity_value, combined_warnings)
            return
        if decision.kind == PlanDecisionKind.SKIP:
            self._builder.add_skip(validation.line_no, identity_value, combined_warnings)
            return

        if decision.desired_state is None or decision.changes is None or decision.resource_id is None:
            raise ValueError("PlanDecision for create/update must include desired_state, changes, and resource_id")

        plan_item = PlanItem(
            row_id=f"line:{validation.line_no}",
            line_no=validation.line_no,
            op=Operation.CREATE if decision.kind == PlanDecisionKind.CREATE else Operation.UPDATE,
            resource_id=decision.resource_id,
            desired_state=decision.desired_state,
            changes=decision.changes,
            source_ref=decision.source_ref,
            secret_fields=decision.secret_fields,
        )
        self._builder.add_plan_item(plan_item)
