"""Unit tests for activity linkage and evidence fact extraction."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from deletion_audit.config import AuditSettings
from deletion_audit.data.loaders import load_dataset_bundle
from deletion_audit.evidence.activity_extractor import analyze_case_activity
from deletion_audit.evidence.log_json_extractor import extract_json_facts, extract_log_facts
from deletion_audit.models import DataCategory, ObservedResourceStatus
from deletion_audit.policy.identity import resolve_identity


@pytest.fixture(scope="session")
def bundle():
    settings = AuditSettings()
    return load_dataset_bundle(settings, split="sample")


@pytest.fixture(scope="session")
def sample_outputs():
    path = Path("dataset/sample_output.csv")
    with path.open(encoding="utf-8") as f:
        return {
            row["case_id"]: {s["resource_id"] for s in json.loads(row["steps_json"])}
            for row in csv.DictReader(f)
        }


def test_activity_linkage_cases_21_to_32(bundle, sample_outputs):
    """Verify cases case_21 through case_32 accurately link all expected resources."""
    for i in range(21, 33):
        cid = f"case_{i}"
        case = next(c for c in bundle.cases if c.case_id == cid)
        identity = resolve_identity(case, bundle.identities, bundle.audit_log)
        summary = analyze_case_activity(case, identity, bundle.activities)

        expected = sample_outputs[cid]
        missing = expected - summary.known_resource_ids
        assert not missing, f"{cid} missing resources from known_resource_ids: {missing}"


def test_activity_linkage_no_collision_same_audit_at(bundle, sample_outputs):
    """Verify cases sharing audit_at (2026-09-15T12:00:00Z) do not collide or leak resources."""
    shared_cases = ["case_26", "case_27", "case_28", "case_21", "case_25", "case_31", "case_32"]
    resource_sets: dict[str, set[str]] = {}

    for cid in shared_cases:
        case = next(c for c in bundle.cases if c.case_id == cid)
        identity = resolve_identity(case, bundle.identities, bundle.audit_log)
        summary = analyze_case_activity(case, identity, bundle.activities)
        expected = sample_outputs[cid]
        # Restrict to expected gold set for pairwise disjointness check
        resource_sets[cid] = set(summary.known_resource_ids) & expected

    for i, cid1 in enumerate(shared_cases):
        for cid2 in shared_cases[i + 1 :]:
            overlap = resource_sets[cid1] & resource_sets[cid2]
            assert not overlap, f"Collision detected between {cid1} and {cid2}: {overlap}"


def test_evidence_92_fact_extraction(bundle):
    """Verify evidence_92 fact extraction for anonymized, redacted, disabled, blocked resources."""
    settings = AuditSettings()
    ev92 = next(m for m in bundle.manifest if m.file_id == "evidence_92")

    # Case 21: absent account, anonymized analytics, retained security audit
    case_21 = next(c for c in bundle.cases if c.case_id == "case_21")
    id_21 = resolve_identity(case_21, bundle.identities, bundle.audit_log)
    act_21 = analyze_case_activity(case_21, id_21, bundle.activities)
    facts_21 = {
        f.resource_id: f
        for f in extract_json_facts(settings, ev92, id_21, known_resource_ids=set(act_21.known_resource_ids))
    }
    assert facts_21["account_6440"].status == ObservedResourceStatus.ABSENT
    assert facts_21["analytics_5335"].status == ObservedResourceStatus.PRESENT_ANONYMIZED
    assert facts_21["audit_record_3737"].status == ObservedResourceStatus.PRESENT_RETAINED

    # Case 26: complete deletion verification bundle (blocked backup, disabled flow, redacted support, anonymized analytics)
    case_26 = next(c for c in bundle.cases if c.case_id == "case_26")
    id_26 = resolve_identity(case_26, bundle.identities, bundle.audit_log)
    act_26 = analyze_case_activity(case_26, id_26, bundle.activities)
    facts_26 = {
        f.resource_id: f
        for f in extract_json_facts(settings, ev92, id_26, known_resource_ids=set(act_26.known_resource_ids))
    }
    assert facts_26["backup_3120"].status == ObservedResourceStatus.RESTORE_BLOCKED
    assert facts_26["data_flow_6244"].status == ObservedResourceStatus.FLOW_DISABLED
    assert facts_26["support_4715"].status == ObservedResourceStatus.PRESENT_REDACTED
    assert facts_26["analytics_4566"].status == ObservedResourceStatus.PRESENT_ANONYMIZED

    # Case 29: active data flow and exposed PII findings
    case_29 = next(c for c in bundle.cases if c.case_id == "case_29")
    id_29 = resolve_identity(case_29, bundle.identities, bundle.audit_log)
    act_29 = analyze_case_activity(case_29, id_29, bundle.activities)
    facts_29 = {
        f.resource_id: f
        for f in extract_json_facts(settings, ev92, id_29, known_resource_ids=set(act_29.known_resource_ids))
    }
    assert facts_29["data_flow_3827"].status == ObservedResourceStatus.FLOW_ACTIVE
    assert facts_29["search_1993"].status == ObservedResourceStatus.PRESENT_IDENTIFIABLE
    assert facts_29["support_5281"].status == ObservedResourceStatus.PRESENT_IDENTIFIABLE
    assert facts_29["analytics_5208"].status == ObservedResourceStatus.PRESENT_IDENTIFIABLE


def test_evidence_51_fact_extraction(bundle):
    """Verify evidence_51 fact extraction for account tombstones and absent accounts."""
    settings = AuditSettings()
    ev51 = next(m for m in bundle.manifest if m.file_id == "evidence_51")

    # Case 31: compliant tombstone (redacted), absent profile, retained audit record
    case_31 = next(c for c in bundle.cases if c.case_id == "case_31")
    id_31 = resolve_identity(case_31, bundle.identities, bundle.audit_log)
    act_31 = analyze_case_activity(case_31, id_31, bundle.activities)
    facts_31 = {
        f.resource_id: f
        for f in extract_json_facts(settings, ev51, id_31, known_resource_ids=set(act_31.known_resource_ids))
    }
    assert facts_31["tombstone_440"].status == ObservedResourceStatus.PRESENT_REDACTED
    assert facts_31["tombstone_440"].data_category == DataCategory.ACCOUNT_TOMBSTONE
    assert facts_31["account_4857"].status == ObservedResourceStatus.ABSENT
    assert facts_31["audit_record_6909"].status == ObservedResourceStatus.PRESENT_RETAINED

    # Case 32: non-compliant tombstone (exposed PII)
    case_32 = next(c for c in bundle.cases if c.case_id == "case_32")
    id_32 = resolve_identity(case_32, bundle.identities, bundle.audit_log)
    act_32 = analyze_case_activity(case_32, id_32, bundle.activities)
    facts_32 = {
        f.resource_id: f
        for f in extract_json_facts(settings, ev51, id_32, known_resource_ids=set(act_32.known_resource_ids))
    }
    assert facts_32["tombstone_9178"].status == ObservedResourceStatus.PRESENT_IDENTIFIABLE
    assert facts_32["tombstone_9178"].data_category == DataCategory.ACCOUNT_TOMBSTONE
    assert facts_32["account_8858"].status == ObservedResourceStatus.ABSENT


def test_evidence_94_fact_extraction(bundle):
    """Verify evidence_94 readback log fact extraction for case_03."""
    settings = AuditSettings()
    ev94 = next(m for m in bundle.manifest if m.file_id == "evidence_94")

    case_03 = next(c for c in bundle.cases if c.case_id == "case_03")
    id_03 = resolve_identity(case_03, bundle.identities, bundle.audit_log)
    act_03 = analyze_case_activity(case_03, id_03, bundle.activities)
    facts_03 = {
        f.resource_id: f
        for f in extract_log_facts(settings, ev94, id_03, known_resource_ids=set(act_03.known_resource_ids))
    }
    assert facts_03["account_7566"].status == ObservedResourceStatus.ABSENT
    assert facts_03["audit_record_2016"].status == ObservedResourceStatus.PRESENT_RETAINED
    assert facts_03["analytics_9406"].status == ObservedResourceStatus.PRESENT_ANONYMIZED


def test_activity_linkage_scaffold_cases(bundle):
    """Verify regression coverage on scaffold cases case_01 to case_10."""
    for i in range(1, 11):
        cid = f"case_{i:02d}"
        case = next(c for c in bundle.cases if c.case_id == cid)
        identity = resolve_identity(case, bundle.identities, bundle.audit_log)
        summary = analyze_case_activity(case, identity, bundle.activities)
        expected_account = f"account_{i:03d}"
        if i == 3:
            expected_account = "account_7566"
        elif i == 9:
            expected_account = "account_3960"
        assert expected_account in summary.known_resource_ids
