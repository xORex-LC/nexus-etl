from __future__ import annotations

from dataclasses import dataclass

from connector.domain.models import MatchStatus, ValidationRowResult
from connector.domain.planning.protocols import PlanDecision, PlanDecisionKind, PlanningPolicyProtocol
from connector.datasets.employees.projector import EmployeesProjector
from connector.domain.planning.employees.decision import DecisionOutcome, EmployeeDecisionPolicy
from connector.domain.planning.employees.differ import EmployeeDiffer
from connector.domain.planning.employees.matcher import EmployeeMatcher


@dataclass
class EmployeesPlanningPolicy(PlanningPolicyProtocol):
    """
    Назначение/ответственность:
        Политика планирования для employees, инкапсулирует matcher/differ/decision/projector.
    Взаимодействия:
        Используется GenericPlanner; не выполняет IO.
    Ограничения:
        Ожидает валидированные сущности.
    """

    projector: EmployeesProjector
    matcher: EmployeeMatcher
    differ: EmployeeDiffer
    decision: EmployeeDecisionPolicy

    def decide(self, validated_entity, validation: ValidationRowResult) -> PlanDecision:
        """
        Назначение:
            Вернуть решение по одной строке employees.
        Контракт (вход/выход):
            - Вход: валидированная сущность + ValidationRowResult.
            - Выход: PlanDecision (create/update/skip/conflict).
        Ошибки/исключения:
            Пробрасывает исключения matcher/differ/decision при фатальных ошибках.
        """
        desired_state = self.projector.to_desired_state(validated_entity)
        identity = self.projector.to_identity(validated_entity, validation)
        source_ref = self.projector.to_source_ref(identity)

        match_result = self.matcher.match(identity)
        if match_result.status == MatchStatus.CONFLICT:
            return PlanDecision(
                kind=PlanDecisionKind.CONFLICT,
                identity=identity,
                source_ref=source_ref,
                secret_fields=[],
                reason_code="MATCH_CONFLICT",
                message="multiple candidates found",
            )

        changes = self.differ.calculate_changes(match_result.candidate, desired_state)
        op, resource_id = self.decision.decide(match_result, changes, desired_state)

        if op == DecisionOutcome.SKIP:
            return PlanDecision(
                kind=PlanDecisionKind.SKIP,
                identity=identity,
                source_ref=source_ref,
                secret_fields=[],
                reason_code="NO_CHANGES",
                message="no changes detected",
            )

        decision_kind = PlanDecisionKind.CREATE if op == DecisionOutcome.CREATE else PlanDecisionKind.UPDATE
        if not resource_id:
            raise ValueError("Employee decision returned empty resource_id")

        secret_fields = ["password"] if decision_kind == PlanDecisionKind.CREATE else []
        return PlanDecision(
            kind=decision_kind,
            identity=identity,
            desired_state=desired_state,
            changes=changes,
            resource_id=resource_id,
            source_ref=source_ref,
            secret_fields=secret_fields,
        )
