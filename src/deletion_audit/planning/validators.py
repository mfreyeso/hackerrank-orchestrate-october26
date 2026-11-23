"""Deterministic verifier checks for CaseResult schema, ordering, and evidence rules."""

from __future__ import annotations

from deletion_audit.models import (
    ALLOWED_TRIPLES,
    CaseResult,
    DeletionStatus,
    StepPhase,
)
from deletion_audit.planning.ordering import step_sort_key


def validate_case_result(
    result: CaseResult,
    *,
    valid_evidence_ids: set[str] | None = None,
) -> list[str]:
    """Return a list of validation error strings (empty if valid)."""
    errors: list[str] = []

    if result.deletion_status == DeletionStatus.NOT_APPLICABLE:
        if len(result.steps) != 0:
            errors.append(
                f"{result.case_id}: NOT_APPLICABLE must have 0 steps, got {len(result.steps)}"
            )
        return errors

    if len(result.steps) == 0:
        errors.append(f"{result.case_id}: {result.deletion_status} must have at least 1 step")
        return errors

    # Check consecutive numbering starting at 1
    expected_nos = list(range(1, len(result.steps) + 1))
    actual_nos = [s.step_no for s in result.steps]
    if actual_nos != expected_nos:
        errors.append(
            f"{result.case_id}: step_no sequence {actual_nos} is not consecutive 1..{len(result.steps)}"
        )

    # Check canonical ordering
    sort_keys = [step_sort_key(s) for s in result.steps]
    if sort_keys != sorted(sort_keys):
        errors.append(f"{result.case_id}: steps are not in canonical (phase, op, system, resource) order")

    # Check phase and evidence_id rules per status
    for step in result.steps:
        triple = (step.phase, step.operation, step.state)
        if triple not in ALLOWED_TRIPLES:
            errors.append(f"{result.case_id}: illegal triple {triple}")

        if result.deletion_status == DeletionStatus.COMPLETE:
            if step.phase != StepPhase.VERIFICATION:
                errors.append(
                    f"{result.case_id}: COMPLETE case contains non-VERIFICATION step {step.phase}"
                )
            if not step.evidence_id:
                errors.append(
                    f"{result.case_id}: COMPLETE verification step {step.step_no} missing evidence_id"
                )
            elif valid_evidence_ids is not None and step.evidence_id not in valid_evidence_ids:
                errors.append(
                    f"{result.case_id}: step {step.step_no} cites unknown/post-cutoff evidence_id '{step.evidence_id}'"
                )
        elif result.deletion_status == DeletionStatus.INCOMPLETE:
            if step.phase == StepPhase.FINDING:
                if not step.evidence_id:
                    errors.append(
                        f"{result.case_id}: INCOMPLETE finding step {step.step_no} missing evidence_id"
                    )
                elif valid_evidence_ids is not None and step.evidence_id not in valid_evidence_ids:
                    errors.append(
                        f"{result.case_id}: step {step.step_no} cites unknown/post-cutoff evidence_id '{step.evidence_id}'"
                    )
            else:
                if step.evidence_id != "":
                    errors.append(
                        f"{result.case_id}: INCOMPLETE {step.phase} step {step.step_no} must have empty evidence_id, got '{step.evidence_id}'"
                    )

    if result.deletion_status == DeletionStatus.INCOMPLETE:
        has_finding = any(s.phase == StepPhase.FINDING for s in result.steps)
        has_remediation = any(s.phase == StepPhase.REMEDIATION for s in result.steps)
        has_verification = any(s.phase == StepPhase.VERIFICATION for s in result.steps)
        if not (has_finding and has_remediation and has_verification):
            errors.append(
                f"{result.case_id}: INCOMPLETE case must include FINDING, REMEDIATION, and VERIFICATION phases"
            )

    return errors
