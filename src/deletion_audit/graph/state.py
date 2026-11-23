"""Typed state definitions and explicit reducers for the per-case LangGraph workflow."""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from deletion_audit.models import (
    Case,
    CaseResult,
    EvidenceFact,
    EvidenceManifestItem,
    PolicyDecision,
    ResolvedIdentity,
    ResourceState,
    SystemActivityRow,
)


def merge_evidence_facts(
    existing: list[EvidenceFact],
    incoming: list[EvidenceFact],
) -> list[EvidenceFact]:
    """Deduplicating reducer for EvidenceFact lists."""
    combined = list(existing) + list(incoming)
    seen: set[tuple[str, str, str, str]] = set()
    unique: list[EvidenceFact] = []
    for fact in combined:
        key = (fact.evidence_id, fact.system_id, fact.resource_id, fact.status.value)
        if key not in seen:
            seen.add(key)
            unique.append(fact)
    return unique


class CaseGraphState(TypedDict, total=False):
    """TypedDict state for a single deletion-audit case graph."""

    case: Case
    identity: ResolvedIdentity
    pruned_manifest: list[EvidenceManifestItem]
    eligible_manifest: list[EvidenceManifestItem]
    workflow_activities: list[SystemActivityRow]
    post_report_activities: list[SystemActivityRow]
    known_resource_ids: list[str]
    delete_targeted_resources: list[str]
    has_drop_account_activity: bool
    classified_non_deletion: bool
    facts: Annotated[list[EvidenceFact], merge_evidence_facts]
    resource_states: list[ResourceState]
    policy_decisions: list[PolicyDecision]
    result: CaseResult
    validation_errors: Annotated[list[str], operator.add]
    retry_count: int
    needs_rerun: bool
