"""Deterministic step planner producing CaseResult from PolicyDecisions."""

from __future__ import annotations

from deletion_audit.models import (
    CaseResult,
    DeletionStatus,
    PolicyDecision,
    Step,
    StepPhase,
)
from deletion_audit.planning.ordering import canonical_sort_steps


def build_case_plan(
    case_id: str,
    decisions: tuple[PolicyDecision, ...],
    *,
    authorizes_deletion: bool = True,
) -> CaseResult:
    """Emit canonical FINDING / REMEDIATION / VERIFICATION steps and deletion_status.

    Evidence citation rules:
    - NOT_APPLICABLE: deletion_status=NOT_APPLICABLE, steps=[]
    - COMPLETE: all decisions compliant; emit VERIFICATION steps only, citing evidence_id.
    - INCOMPLETE: at least one non-compliant decision; emit FINDING steps (citing evidence_id),
      REMEDIATION steps (empty evidence_id), and post-remediation VERIFICATION steps (empty evidence_id).
    """
    if not authorizes_deletion:
        return CaseResult(
            case_id=case_id,
            deletion_status=DeletionStatus.NOT_APPLICABLE,
            steps=(),
        )

    non_compliant = [d for d in decisions if not d.is_compliant]
    is_complete = len(non_compliant) == 0 and len(decisions) > 0

    raw_steps: list[Step] = []

    if is_complete:
        for d in decisions:
            if d.verification_op is not None and d.verification_state is not None:
                raw_steps.append(
                    Step(
                        step_no=1,
                        phase=StepPhase.VERIFICATION,
                        system_id=d.system_id,
                        resource_id=d.resource_id,
                        operation=d.verification_op,
                        state=d.verification_state,
                        evidence_id=d.evidence_id,
                    )
                )
        ordered = canonical_sort_steps(raw_steps)
        return CaseResult(
            case_id=case_id,
            deletion_status=DeletionStatus.COMPLETE,
            steps=ordered,
        )

    # INCOMPLETE case
    for d in non_compliant:
        if d.finding_op is not None and d.finding_state is not None:
            raw_steps.append(
                Step(
                    step_no=1,
                    phase=StepPhase.FINDING,
                    system_id=d.system_id,
                    resource_id=d.resource_id,
                    operation=d.finding_op,
                    state=d.finding_state,
                    evidence_id=d.evidence_id,
                )
            )
        if d.remediation_op is not None and d.remediation_state is not None:
            raw_steps.append(
                Step(
                    step_no=1,
                    phase=StepPhase.REMEDIATION,
                    system_id=d.system_id,
                    resource_id=d.resource_id,
                    operation=d.remediation_op,
                    state=d.remediation_state,
                    evidence_id="",
                )
            )

    for d in decisions:
        if d.verification_op is not None and d.verification_state is not None:
            raw_steps.append(
                Step(
                    step_no=1,
                    phase=StepPhase.VERIFICATION,
                    system_id=d.system_id,
                    resource_id=d.resource_id,
                    operation=d.verification_op,
                    state=d.verification_state,
                    evidence_id="",
                )
            )

    ordered = canonical_sort_steps(raw_steps)
    return CaseResult(
        case_id=case_id,
        deletion_status=DeletionStatus.INCOMPLETE,
        steps=ordered,
    )
