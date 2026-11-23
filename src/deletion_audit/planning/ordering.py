"""Canonical step ordering and consecutive step_no numbering."""

from __future__ import annotations

from collections.abc import Sequence

from deletion_audit.models import OPERATION_ORDER, PHASE_ORDER, Step, StepOperation, StepPhase

_PHASE_RANK: dict[StepPhase, int] = {phase: idx for idx, phase in enumerate(PHASE_ORDER)}
_OP_RANK: dict[StepOperation, int] = {op: idx for idx, op in enumerate(OPERATION_ORDER)}


def step_sort_key(step: Step) -> tuple[int, int, str, str]:
    """Return canonical sort key: (phase_rank, operation_rank, system_id, resource_id)."""
    return (
        _PHASE_RANK[step.phase],
        _OP_RANK[step.operation],
        step.system_id,
        step.resource_id,
    )


def canonical_sort_steps(steps: Sequence[Step]) -> tuple[Step, ...]:
    """Sort steps in canonical order, deduplicate on (phase, system_id, resource_id, operation),
    and re-number step_no starting at 1 consecutively.
    """
    seen: set[tuple[StepPhase, str, str, StepOperation]] = set()
    unique_steps: list[Step] = []
    for step in sorted(steps, key=step_sort_key):
        dedup_key = (step.phase, step.system_id, step.resource_id, step.operation)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        unique_steps.append(step)

    return tuple(
        Step(
            step_no=idx,
            phase=step.phase,
            system_id=step.system_id,
            resource_id=step.resource_id,
            operation=step.operation,
            state=step.state,
            evidence_id=step.evidence_id,
        )
        for idx, step in enumerate(unique_steps, start=1)
    )
