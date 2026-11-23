"""Unit and property-based tests for state-at-audit_at reconstruction, planning, and canonical ordering."""

from __future__ import annotations

from datetime import UTC, datetime

from hypothesis import given
from hypothesis import strategies as st

from deletion_audit.models import (
    ALLOWED_TRIPLES,
    DataCategory,
    DeletionStatus,
    EvidenceFact,
    ObservedResourceStatus,
    Step,
)
from deletion_audit.planning import (
    build_case_plan,
    canonical_sort_steps,
    reconstruct_resource_states,
    step_sort_key,
)


def test_reconstruct_resource_states_cutoff_and_replication_drift() -> None:
    audit_at = datetime(2026, 9, 8, 13, 40, tzinfo=UTC)
    snap_time = datetime(2026, 9, 2, 23, 0, tzinfo=UTC)
    future_time = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)

    facts = (
        # Primary says ABSENT at snap_time
        EvidenceFact(
            evidence_id="evidence_54",
            captured_at=snap_time,
            system_id="account_service",
            resource_id="account_005",
            data_category=DataCategory.USER_PROFILE,
            status=ObservedResourceStatus.ABSENT,
        ),
        # Failover replica at same snap_time still has PRESENT_IDENTIFIABLE (replication drift!)
        EvidenceFact(
            evidence_id="evidence_54",
            captured_at=snap_time,
            system_id="account_service",
            resource_id="account_005",
            data_category=DataCategory.USER_PROFILE,
            status=ObservedResourceStatus.PRESENT_IDENTIFIABLE,
            is_replica_only=True,
        ),
        # Future fact after audit_at claiming ABSENT (must be ignored!)
        EvidenceFact(
            evidence_id="evidence_52",
            captured_at=future_time,
            system_id="account_service",
            resource_id="account_005",
            data_category=DataCategory.USER_PROFILE,
            status=ObservedResourceStatus.ABSENT,
        ),
        # Workflow claim only (must be ignored!)
        EvidenceFact(
            evidence_id="activity_3342",
            captured_at=snap_time,
            system_id="account_service",
            resource_id="account_005",
            data_category=DataCategory.USER_PROFILE,
            status=ObservedResourceStatus.ABSENT,
            is_claim_only=True,
        ),
    )

    states = reconstruct_resource_states(facts, audit_at)
    assert len(states) == 1
    assert states[0].system_id == "account_service"
    assert states[0].resource_id == "account_005"
    assert states[0].status == ObservedResourceStatus.PRESENT_IDENTIFIABLE
    assert states[0].evidence_id == "evidence_54"


def test_reconstruct_resource_states_superseded_pre_request_snapshots() -> None:
    """Historical snapshots captured before requested_at must be superseded by post-request evidence."""
    req_at = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)
    audit_at = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)

    pre_req_time = datetime(2026, 2, 13, 8, 0, tzinfo=UTC)
    post_req_time = datetime(2026, 9, 15, 11, 44, 55, tzinfo=UTC)

    facts = (
        # Pre-request historical object presence from February (superseded!)
        EvidenceFact(
            evidence_id="evidence_46",
            captured_at=pre_req_time,
            system_id="object_storage",
            resource_id="object_19",
            data_category=DataCategory.USER_PROFILE,
            status=ObservedResourceStatus.PRESENT_IDENTIFIABLE,
            notes="Historical storage screenshot",
        ),
        # Post-request authoritative account lookup from September
        EvidenceFact(
            evidence_id="evidence_92",
            captured_at=post_req_time,
            system_id="account_service",
            resource_id="account_6440",
            data_category=DataCategory.USER_PROFILE,
            status=ObservedResourceStatus.ABSENT,
            notes="service_resource_export account_service.profile_lookups",
        ),
    )

    states = reconstruct_resource_states(facts, audit_at, requested_at=req_at)
    assert len(states) == 1
    assert states[0].system_id == "account_service"
    assert states[0].resource_id == "account_6440"
    assert states[0].status == ObservedResourceStatus.ABSENT
    assert states[0].evidence_id == "evidence_92"


def test_reconstruct_resource_states_replica_drift_overrides_subsequent_inferred_absence() -> None:
    """Replica drift observed in failover replica cannot be erased by a later inferred absence in primary."""
    req_at = datetime(2026, 8, 27, 14, 0, tzinfo=UTC)
    audit_at = datetime(2026, 9, 8, 13, 40, tzinfo=UTC)

    replica_snap_time = datetime(2026, 9, 2, 23, 0, tzinfo=UTC)
    inventory_snap_time = datetime(2026, 9, 5, 7, 18, 1, tzinfo=UTC)

    facts = (
        # Failover replica on Sept 2 exposes account_005
        EvidenceFact(
            evidence_id="evidence_54",
            captured_at=replica_snap_time,
            system_id="account_service",
            resource_id="account_005",
            data_category=DataCategory.USER_PROFILE,
            status=ObservedResourceStatus.PRESENT_IDENTIFIABLE,
            is_replica_only=True,
            notes="SQL table customer_profiles_failover_replica",
        ),
        # Primary inventory snapshot on Sept 5 only checked primary table, not replica
        EvidenceFact(
            evidence_id="evidence_90",
            captured_at=inventory_snap_time,
            system_id="account_service",
            resource_id="account_005",
            data_category=DataCategory.USER_PROFILE,
            status=ObservedResourceStatus.ABSENT,
            notes="Account profile absent from SQL snapshot",
        ),
    )

    states = reconstruct_resource_states(facts, audit_at, requested_at=req_at)
    assert len(states) == 1
    assert states[0].system_id == "account_service"
    assert states[0].resource_id == "account_005"
    assert states[0].status == ObservedResourceStatus.PRESENT_IDENTIFIABLE
    assert states[0].evidence_id == "evidence_54"


def test_reconstruct_resource_states_restore_risk_and_account_disambiguation() -> None:
    """Restore risk is preserved and spurious inferred account is pruned in favor of grounded account."""
    req_at = datetime(2026, 8, 20, 10, 0, tzinfo=UTC)
    audit_at = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
    obs_time = datetime(2026, 9, 15, 11, 59, 39, tzinfo=UTC)

    facts = (
        # Grounded account fact from observability trace
        EvidenceFact(
            evidence_id="evidence_01",
            captured_at=obs_time,
            system_id="account_service",
            resource_id="account_4092",
            data_category=DataCategory.USER_PROFILE,
            status=ObservedResourceStatus.ABSENT,
            notes="Log event profile_lookup_completed",
        ),
        # Spurious inferred absence for unrelated account from negative snapshot scan
        EvidenceFact(
            evidence_id="evidence_51",
            captured_at=datetime(2026, 9, 15, 12, 0, tzinfo=UTC),
            system_id="account_service",
            resource_id="account_6523",
            data_category=DataCategory.USER_PROFILE,
            status=ObservedResourceStatus.ABSENT,
            notes="Absent from JSON customer_profiles snapshot",
        ),
        # Restore risk on backup archive
        EvidenceFact(
            evidence_id="evidence_01",
            captured_at=obs_time,
            system_id="backup_service",
            resource_id="backup_3245",
            data_category=DataCategory.BACKUP_ARCHIVE,
            status=ObservedResourceStatus.RESTORE_ACTIVE,
            notes="Log event backup_restore_verified",
        ),
    )

    states = reconstruct_resource_states(facts, audit_at, requested_at=req_at)
    by_sys = {s.system_id: s for s in states}
    assert len(states) == 2
    assert by_sys["account_service"].resource_id == "account_4092"
    assert by_sys["backup_service"].resource_id == "backup_3245"
    assert by_sys["backup_service"].status == ObservedResourceStatus.RESTORE_ACTIVE


def test_not_applicable_short_circuit_plan() -> None:
    res = build_case_plan("case_000", (), authorizes_deletion=False)
    assert res.deletion_status == DeletionStatus.NOT_APPLICABLE
    assert res.steps == ()


@given(
    st.lists(
        st.sampled_from(sorted(ALLOWED_TRIPLES)),
        min_size=1,
        max_size=20,
    ),
    st.lists(
        st.sampled_from(["account_service", "search_service", "support_platform", "backup_service"]),
        min_size=1,
        max_size=20,
    ),
)
def test_canonical_sort_steps_property(
    triples: list[tuple[str, str, str]],
    systems: list[str],
) -> None:
    raw_steps: list[Step] = []
    for idx, (phase, op, state) in enumerate(triples):
        sys_id = systems[idx % len(systems)]
        raw_steps.append(
            Step(
                step_no=99,
                phase=phase,  # type: ignore[arg-type]
                system_id=sys_id,
                resource_id=f"res_{idx:03d}",
                operation=op,  # type: ignore[arg-type]
                state=state,  # type: ignore[arg-type]
                evidence_id="evidence_01",
            )
        )

    ordered = canonical_sort_steps(raw_steps)
    # Consecutive numbering from 1
    assert [s.step_no for s in ordered] == list(range(1, len(ordered) + 1))
    # Monotonic sort keys
    keys = [step_sort_key(s) for s in ordered]
    assert keys == sorted(keys)
    # Idempotence
    assert canonical_sort_steps(ordered) == ordered
