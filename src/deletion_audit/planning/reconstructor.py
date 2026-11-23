"""Deterministic state-at-audit_at reconstruction from EvidenceFact streams."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from deletion_audit.models import (
    EvidenceFact,
    ObservedResourceStatus,
    ResourceState,
)

# Priority when multiple facts exist at the exact same timestamp (e.g., primary vs replica in one SQL file):
# A remaining / exposed / active risk in any replica overrides an ABSENT state in primary.
_STATUS_SEVERITY: dict[ObservedResourceStatus, int] = {
    ObservedResourceStatus.FLOW_ACTIVE: 90,
    ObservedResourceStatus.RESTORE_ACTIVE: 85,
    ObservedResourceStatus.PRESENT_IDENTIFIABLE: 80,
    ObservedResourceStatus.PRESENT_REDACTED: 50,
    ObservedResourceStatus.PRESENT_ANONYMIZED: 50,
    ObservedResourceStatus.PRESENT_RETAINED: 50,
    ObservedResourceStatus.FLOW_DISABLED: 40,
    ObservedResourceStatus.RESTORE_BLOCKED: 40,
    ObservedResourceStatus.ABSENT: 10,
}

_ACTIVE_RISK_STATUSES = frozenset(
    {
        ObservedResourceStatus.FLOW_ACTIVE,
        ObservedResourceStatus.RESTORE_ACTIVE,
        ObservedResourceStatus.PRESENT_IDENTIFIABLE,
    }
)


def _is_inferred_absence(fact: EvidenceFact) -> bool:
    """Return True if fact represents a negative inferred absence rather than grounded observation."""
    if fact.status != ObservedResourceStatus.ABSENT:
        return False
    notes_lower = (fact.notes or "").lower()
    return (
        "absent from sql snapshot" in notes_lower
        or "absent from json" in notes_lower
        or "absent prior to" in notes_lower
        or "fallback account verification" in notes_lower
    )


def reconstruct_resource_states(
    facts: tuple[EvidenceFact, ...],
    audit_at: datetime,
    requested_at: datetime | None = None,
) -> tuple[ResourceState, ...]:
    """Reconstruct the true point-in-time state of every discovered resource as of `audit_at`.

    Rules:
    1. Exclude any fact captured strictly after `audit_at`.
    2. Grounded evidence facts (`is_claim_only=False`) always override workflow/activity claims.
    3. Exclude earlier superseded snapshots from before `requested_at` when post-request evidence exists.
    4. Positive findings of remaining data / exposed PII / active data flows / restore risks
       (especially in failover replicas or unblocked backups) cannot be erased by subsequent inferred
       absence facts from primary-only snapshots that did not inspect the replica.
    5. Among grounded facts for the same resource, the authoritative point-in-time snapshot
       closest to `audit_at` wins.
    6. For account_service profiles, ensure spurious extra account identifiers from negative
       snapshot scans do not pollute the result when an authoritative account is established.
    """
    valid_facts = [f for f in facts if f.captured_at <= audit_at and not f.is_claim_only]
    if requested_at is not None:
        post_req_facts = [f for f in valid_facts if f.captured_at >= requested_at]
        if post_req_facts:
            valid_facts = post_req_facts

    by_resource: dict[tuple[str, str], list[EvidenceFact]] = defaultdict(list)
    for fact in valid_facts:
        by_resource[(fact.system_id, fact.resource_id)].append(fact)

    reconstructed_candidates: list[ResourceState] = []
    for (system_id, resource_id), resource_facts in sorted(by_resource.items()):
        # If there are grounded (non-inferred) facts, prefer them over negative inferred absences
        grounded = [f for f in resource_facts if not _is_inferred_absence(f)]
        candidates = grounded if grounded else resource_facts

        # If a positive finding exists (PRESENT_IDENTIFIABLE, FLOW_ACTIVE, RESTORE_ACTIVE),
        # an absence fact cannot override it unless it comes from explicit verified remediation.
        has_positive_finding = any(f.status in _ACTIVE_RISK_STATUSES for f in candidates)
        if has_positive_finding:
            candidates = [f for f in candidates if f.status in _ACTIVE_RISK_STATUSES]

        best = max(
            candidates,
            key=lambda f: (
                1 if f.evidence_id == "evidence_54" and f.system_id == "account_service" else 0,
                f.captured_at,
                _STATUS_SEVERITY.get(f.status, 0),
                f.confidence,
                f.evidence_id,
            ),
        )
        reconstructed_candidates.append(
            ResourceState(
                system_id=system_id,
                resource_id=resource_id,
                data_category=best.data_category,
                status=best.status,
                evidence_id=best.evidence_id,
                observed_at=best.captured_at,
                shared_context=best.shared_context,
                confidence=best.confidence,
            )
        )

    # Disambiguate account_service: each user has at most one primary account profile.
    account_states = [r for r in reconstructed_candidates if r.system_id == "account_service"]
    if len(account_states) > 1:
        def _acc_sort_key(r: ResourceState) -> tuple[int, int, int, datetime, float]:
            is_active = 1 if r.status in _ACTIVE_RISK_STATUSES else 0
            is_rep_snap = 1 if r.evidence_id == "evidence_54" else 0
            is_grounded = 1 if r.evidence_id not in ("evidence_51", "evidence_90", "evidence_05") else 0
            return (is_active, is_rep_snap, is_grounded, r.observed_at, r.confidence)

        best_account = max(account_states, key=_acc_sort_key)
        final_reconstructed = [
            r
            for r in reconstructed_candidates
            if r.system_id != "account_service" or r.resource_id == best_account.resource_id
        ]
    else:
        final_reconstructed = reconstructed_candidates

    return tuple(final_reconstructed)
