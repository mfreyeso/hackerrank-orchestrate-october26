"""Unit tests for deterministic identity resolution and policy engine (incl. tombstones)."""

from __future__ import annotations

from datetime import UTC, datetime

from deletion_audit.config import AuditSettings
from deletion_audit.data import load_audit_log, load_deletion_rules, load_identities
from deletion_audit.models import (
    Case,
    DataCategory,
    ObservedResourceStatus,
    ReportedStatus,
    ResourceState,
    StepOperation,
    StepState,
    UserAuditLogEntry,
    UserIdentityRow,
)
from deletion_audit.policy import PolicyEngine, resolve_identity


def test_resolve_identity_with_historical_email_and_audit_cutoff() -> None:
    identities = (
        UserIdentityRow(
            user_id="user_10",
            name="Nadia Petrescu",
            email="n.petrescu@yahoo.com",
            phone="+40 723 481 638",
            email_hash="6385b5b5e70720c197abedd379f714bb84330a9c7bc86bbb4bfbc4405bdba326",
            updated_at=datetime(2026, 4, 12, 14, 38, 26, tzinfo=UTC),
        ),
    )
    audit_log = (
        UserAuditLogEntry(
            audit_id="audit_100",
            user_id="user_10",
            event_time=datetime(2026, 4, 12, 14, 38, 26, tzinfo=UTC),
            field_name="email",
            old_value="nadia.ionescu@yahoo.com",
            new_value="n.petrescu@yahoo.com",
        ),
        # Future change after audit_at must be ignored
        UserAuditLogEntry(
            audit_id="audit_999",
            user_id="user_10",
            event_time=datetime(2026, 12, 1, 0, 0, 0, tzinfo=UTC),
            field_name="email",
            old_value="n.petrescu@yahoo.com",
            new_value="future.nadia@yahoo.com",
        ),
    )
    case = Case(
        case_id="case_10",
        email="nadia.ionescu@yahoo.com",
        requested_at=datetime(2026, 8, 31, 15, 42, tzinfo=UTC),
        reported_status=ReportedStatus.COMPLETE,
        reported_at=datetime(2026, 9, 2, 10, 8, tzinfo=UTC),
        audit_at=datetime(2026, 9, 18, 12, 25, tzinfo=UTC),
        request_text="Please remove records linked to both the old and current addresses.",
    )

    resolved = resolve_identity(case, identities, audit_log)
    assert resolved.user_ids == ("user_10",)
    assert "n.petrescu@yahoo.com" in resolved.current_emails
    assert "nadia.ionescu@yahoo.com" in resolved.historical_emails
    assert "future.nadia@yahoo.com" not in resolved.all_emails
    assert resolved.matches_value("NADIA.IONESCU@YAHOO.COM")
    assert resolved.matches_value("n.petrescu@yahoo.com")
    assert resolved.matches_value("user_10")


def test_resolve_identity_on_real_dataset_case_10() -> None:
    settings = AuditSettings()
    identities = load_identities(settings)
    audit_log = load_audit_log(settings)
    case = Case(
        case_id="case_10",
        email="nadia.ionescu@yahoo.com",
        requested_at=datetime(2026, 8, 31, 15, 42, tzinfo=UTC),
        reported_status=ReportedStatus.COMPLETE,
        reported_at=datetime(2026, 9, 2, 10, 8, tzinfo=UTC),
        audit_at=datetime(2026, 9, 18, 12, 25, tzinfo=UTC),
        request_text="Please remove records linked to both the old and current addresses.",
    )
    resolved = resolve_identity(case, identities, audit_log)
    assert "user_10" in resolved.user_ids
    assert "n.petrescu@yahoo.com" in resolved.all_emails
    assert "nadia.ionescu@yahoo.com" in resolved.all_emails


def test_policy_engine_tombstones_and_categories() -> None:
    settings = AuditSettings()
    rules = load_deletion_rules(settings)
    engine = PolicyEngine(rules)
    ts = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)

    # 1. Compliant tombstone (only user_id retained; direct PII redacted)
    tombstone_ok = ResourceState(
        system_id="identity_service",
        resource_id="tombstone_440",
        data_category=DataCategory.ACCOUNT_TOMBSTONE,
        status=ObservedResourceStatus.PRESENT_REDACTED,
        evidence_id="evidence_51",
        observed_at=ts,
    )
    dec_ok = engine.evaluate(tombstone_ok)
    assert dec_ok.is_compliant is True
    assert dec_ok.verification_op == StepOperation.VERIFY_RECORD_REDACTED
    assert dec_ok.verification_state == StepState.REDACTED

    # 2. Non-compliant tombstone (PII still exposed)
    tombstone_bad = ResourceState(
        system_id="identity_service",
        resource_id="tombstone_9178",
        data_category=DataCategory.ACCOUNT_TOMBSTONE,
        status=ObservedResourceStatus.PRESENT_IDENTIFIABLE,
        evidence_id="evidence_51",
        observed_at=ts,
    )
    dec_bad = engine.evaluate(tombstone_bad)
    assert dec_bad.is_compliant is False
    assert dec_bad.finding_op == StepOperation.REPORT_EXPOSED_PII
    assert dec_bad.remediation_op == StepOperation.REDACT_RECORD
    assert dec_bad.verification_op == StepOperation.VERIFY_RECORD_REDACTED

    # 3. Active data flow vs restore risk
    flow_active = ResourceState(
        system_id="integration_service",
        resource_id="data_flow_9522",
        data_category=DataCategory.DATA_FLOW,
        status=ObservedResourceStatus.FLOW_ACTIVE,
        evidence_id="evidence_03",
        observed_at=ts,
    )
    dec_flow = engine.evaluate(flow_active)
    assert dec_flow.is_compliant is False
    assert dec_flow.finding_op == StepOperation.REPORT_ACTIVE_DATA_FLOW
    assert dec_flow.remediation_op == StepOperation.DISABLE_DATA_FLOW
    assert dec_flow.verification_op == StepOperation.VERIFY_DATA_FLOW_DISABLED

    backup_risk = ResourceState(
        system_id="backup_service",
        resource_id="backup_4978",
        data_category=DataCategory.BACKUP_ARCHIVE,
        status=ObservedResourceStatus.RESTORE_ACTIVE,
        evidence_id="evidence_93",
        observed_at=ts,
    )
    dec_backup = engine.evaluate(backup_risk)
    assert dec_backup.is_compliant is False
    assert dec_backup.finding_op == StepOperation.REPORT_RESTORE_RISK
    assert dec_backup.remediation_op == StepOperation.BLOCK_RESTORE
    assert dec_backup.verification_op == StepOperation.VERIFY_RESTORE_BLOCKED
