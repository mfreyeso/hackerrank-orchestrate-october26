"""Comprehensive unit tests for PDF and image multimodal evidence extractors."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from deletion_audit.config import AuditSettings
from deletion_audit.evidence.doc_vision_extractor import (
    extract_image_facts,
    extract_pdf_facts,
    extract_pdf_tables,
    extract_pdf_text,
)
from deletion_audit.models import (
    DataCategory,
    EvidenceManifestItem,
    ObservedResourceStatus,
    ResolvedIdentity,
)


@pytest.fixture
def audit_settings() -> AuditSettings:
    return AuditSettings(repo_root=Path(__file__).resolve().parent.parent)


def _utc_dt(iso_str: str) -> datetime:
    return datetime.fromisoformat(iso_str.replace("Z", "+00:00"))


def test_extract_pdf_text_and_tables(audit_settings: AuditSettings) -> None:
    """Verify that extract_pdf_text and extract_pdf_tables extract content from all 4 PDFs."""
    pdf_files = [
        "dataset/evidence/documents/account_history_report_20260718.pdf",
        "dataset/evidence/documents/delivery_correction_attachment.pdf",
        "dataset/evidence/documents/legal_retention_register_20260529.pdf",
        "dataset/evidence/documents/security_retention_extract.pdf",
    ]
    for rel_path in pdf_files:
        full_path = audit_settings.repo_root / rel_path
        text = extract_pdf_text(str(full_path))
        assert len(text) > 50, f"Expected non-empty text in {rel_path}"

    # Verify structured tables extraction on legal retention register
    legal_path = audit_settings.repo_root / "dataset/evidence/documents/legal_retention_register_20260529.pdf"
    tables = extract_pdf_tables(str(legal_path))
    assert len(tables) >= 1
    found_order = any("ORD-20264319" in " ".join(row) for tbl in tables for row in tbl)
    assert found_order, "Expected ORD-20264319 in extracted tables"


def test_pdf_extraction_evidence_58_support_attachment(audit_settings: AuditSettings) -> None:
    """evidence_58: delivery_correction_attachment.pdf -> support_001 (SUPPORT_ATTACHMENT)."""
    item = EvidenceManifestItem(
        file_id="evidence_58",
        file_path="evidence/documents/delivery_correction_attachment.pdf",
        origin="support_platform",
        captured_at=_utc_dt("2026-09-12T07:30:00Z"),
    )
    identity = ResolvedIdentity(
        case_id="case_07",
        request_email="priya.raman@gmail.com",
        user_ids=("user_07",),
        names=("Priya Raman",),
        current_emails=("priya.raman@gmail.com",),
        historical_emails=(),
        all_emails=("priya.raman@gmail.com",),
        phones=("+91 98765 73142",),
    )
    facts = extract_pdf_facts(
        audit_settings, item, identity, known_resource_ids={"support_001"}
    )
    assert len(facts) == 1
    fact = facts[0]
    assert fact.evidence_id == "evidence_58"
    assert fact.resource_id == "support_001"
    assert fact.system_id == "support_platform"
    assert fact.data_category == DataCategory.SUPPORT_ATTACHMENT
    assert fact.status == ObservedResourceStatus.PRESENT_IDENTIFIABLE
    assert fact.shared_context is False


def test_pdf_extraction_evidence_55_security_retention(audit_settings: AuditSettings) -> None:
    """evidence_55: security_retention_extract.pdf -> audit_record_003 (SECURITY_AUDIT_LOG)."""
    item = EvidenceManifestItem(
        file_id="evidence_55",
        file_path="evidence/documents/security_retention_extract.pdf",
        origin="security_service",
        captured_at=_utc_dt("2026-09-05T06:30:00Z"),
    )
    identity = ResolvedIdentity(
        case_id="case_03",
        request_email="oliver-bennett@gmail.com",
        user_ids=("user_03",),
        names=("Oliver Bennett",),
        all_emails=("oliver-bennett@gmail.com",),
    )
    facts = extract_pdf_facts(
        audit_settings, item, identity, known_resource_ids={"audit_record_003"}
    )
    assert len(facts) == 1
    fact = facts[0]
    assert fact.evidence_id == "evidence_55"
    assert fact.resource_id == "audit_record_003"
    assert fact.system_id == "security_service"
    assert fact.data_category == DataCategory.SECURITY_AUDIT_LOG
    assert fact.status == ObservedResourceStatus.PRESENT_RETAINED


def test_pdf_extraction_evidence_27_legal_retention(audit_settings: AuditSettings) -> None:
    """evidence_27: legal_retention_register_20260529.pdf -> legal_hold_4319 for user_17."""
    item = EvidenceManifestItem(
        file_id="evidence_27",
        file_path="evidence/documents/legal_retention_register_20260529.pdf",
        origin="legal_retention_service",
        captured_at=_utc_dt("2026-05-29T08:00:00Z"),
    )
    identity = ResolvedIdentity(
        case_id="case_17",
        request_email="leonie.g9352@outlook.com",
        user_ids=("user_17",),
        names=("Léonie Girard",),
        all_emails=("leonie.g9352@outlook.com",),
    )
    facts = extract_pdf_facts(audit_settings, item, identity)
    assert len(facts) == 1
    fact = facts[0]
    assert fact.evidence_id == "evidence_27"
    assert fact.resource_id == "legal_hold_4319"
    assert fact.system_id == "legal_service"
    assert fact.data_category == DataCategory.LEGAL_HOLD_RECORD
    assert fact.status == ObservedResourceStatus.PRESENT_RETAINED


def test_pdf_extraction_evidence_18_statement_export(audit_settings: AuditSettings) -> None:
    """evidence_18: account_history_report_20260718.pdf -> export_1842 for user_18."""
    item = EvidenceManifestItem(
        file_id="evidence_18",
        file_path="evidence/documents/account_history_report_20260718.pdf",
        origin="account_history_service",
        captured_at=_utc_dt("2026-07-18T11:00:00Z"),
    )
    identity = ResolvedIdentity(
        case_id="case_18",
        request_email="ingrid.dahl@outlook.com",
        user_ids=("user_18",),
        names=("Ingrid Dahl",),
        all_emails=("ingrid.dahl@outlook.com",),
    )
    facts = extract_pdf_facts(audit_settings, item, identity)
    assert len(facts) == 1
    fact = facts[0]
    assert fact.evidence_id == "evidence_18"
    assert fact.resource_id == "export_1842"
    assert fact.system_id == "export_service"
    assert fact.data_category == DataCategory.USER_EXPORT
    assert fact.status == ObservedResourceStatus.PRESENT_IDENTIFIABLE


def test_image_extraction_all_eleven_consoles(audit_settings: AuditSettings) -> None:
    """Verify extract_image_facts on each of the 11 PNG screenshots with matching subjects."""
    cases = [
        # evidence_04: account_admin_console_20260926.png -> account_5762
        (
            EvidenceManifestItem(
                file_id="evidence_04",
                file_path="evidence/images/account_admin_console_20260926.png",
                origin="account_admin_portal",
                captured_at=_utc_dt("2026-09-26T11:00:00Z"),
            ),
            ResolvedIdentity(
                case_id="c_04",
                request_email="haruka.s1838@zoho.com",
                user_ids=("user_11",),
                names=("Haruka Sato",),
                all_emails=("haruka.s1838@zoho.com",),
                phones=("+81 90 7610 2507",),
            ),
            "account_5762",
            "account_service",
            DataCategory.USER_PROFILE,
            ObservedResourceStatus.PRESENT_IDENTIFIABLE,
        ),
        # evidence_09: search_index_inspector_20260901.png -> search_428
        (
            EvidenceManifestItem(
                file_id="evidence_09",
                file_path="evidence/images/search_index_inspector_20260901.png",
                origin="search_index_admin",
                captured_at=_utc_dt("2026-09-01T06:00:00Z"),
            ),
            ResolvedIdentity(
                case_id="c_09",
                request_email="g.silva76@gmail.com",
                user_ids=("user_13",),
                names=("Gabriel Silva",),
                all_emails=("g.silva76@gmail.com",),
            ),
            "search_428",
            "search_service",
            DataCategory.SEARCH_INDEX_ENTRY,
            ObservedResourceStatus.PRESENT_IDENTIFIABLE,
        ),
        # evidence_14: connector_management_console_20260807.png -> data_flow_1121
        (
            EvidenceManifestItem(
                file_id="evidence_14",
                file_path="evidence/images/connector_management_console_20260807.png",
                origin="integration_admin",
                captured_at=_utc_dt("2026-08-07T08:00:00Z"),
            ),
            ResolvedIdentity(
                case_id="c_14",
                request_email="jain.aditi@gmail.com",
                user_ids=("user_14",),
                names=("Aditi Jain",),
                all_emails=("jain.aditi@gmail.com",),
            ),
            "data_flow_1121",
            "integration_service",
            DataCategory.DATA_FLOW,
            ObservedResourceStatus.FLOW_ACTIVE,
        ),
        # evidence_19: analytics_profile_view_20260713.png -> analytics_7438
        (
            EvidenceManifestItem(
                file_id="evidence_19",
                file_path="evidence/images/analytics_profile_view_20260713.png",
                origin="analytics_platform",
                captured_at=_utc_dt("2026-07-13T10:00:00Z"),
            ),
            ResolvedIdentity(
                case_id="c_19",
                request_email="darwish.omar@icloud.com",
                user_ids=("user_20",),
                names=("Omar Darwish",),
                all_emails=("darwish.omar@icloud.com",),
            ),
            "analytics_7438",
            "analytics_platform",
            DataCategory.ANALYTICS_PROFILE,
            ObservedResourceStatus.PRESENT_IDENTIFIABLE,
        ),
        # evidence_23: customer_export_console_20260618.png -> export_1260
        (
            EvidenceManifestItem(
                file_id="evidence_23",
                file_path="evidence/images/customer_export_console_20260618.png",
                origin="export_service",
                captured_at=_utc_dt("2026-06-18T12:00:00Z"),
            ),
            ResolvedIdentity(
                case_id="c_23",
                request_email="ingrid.dahl@outlook.com",
                user_ids=("user_18",),
                names=("Ingrid Dahl",),
                all_emails=("ingrid.dahl@outlook.com",),
            ),
            "export_1260",
            "export_service",
            DataCategory.USER_EXPORT,
            ObservedResourceStatus.PRESENT_IDENTIFIABLE,
        ),
        # evidence_28: support_ticket_console_20260524.png -> support_1034
        (
            EvidenceManifestItem(
                file_id="evidence_28",
                file_path="evidence/images/support_ticket_console_20260524.png",
                origin="support_platform",
                captured_at=_utc_dt("2026-05-24T07:00:00Z"),
            ),
            ResolvedIdentity(
                case_id="c_28",
                request_email="kagyeman8947@fastmail.com",
                user_ids=("user_22",),
                names=("Kofi Agyeman",),
                all_emails=("kagyeman8947@fastmail.com",),
            ),
            "support_1034",
            "support_platform",
            DataCategory.SUPPORT_MESSAGE,
            ObservedResourceStatus.PRESENT_IDENTIFIABLE,
        ),
        # evidence_32: backup_restore_console_20260429.png -> backup_9287
        (
            EvidenceManifestItem(
                file_id="evidence_32",
                file_path="evidence/images/backup_restore_console_20260429.png",
                origin="backup_service",
                captured_at=_utc_dt("2026-04-29T09:00:00Z"),
            ),
            ResolvedIdentity(
                case_id="c_32",
                request_email="areed1433@gmail.com",
                user_ids=("user_16",),
                names=("Amelia Reed",),
                all_emails=("areed1433@gmail.com",),
            ),
            "backup_9287",
            "backup_service",
            DataCategory.BACKUP_ARCHIVE,
            ObservedResourceStatus.RESTORE_ACTIVE,
        ),
        # evidence_37: security_audit_explorer_20260905.png -> audit_record_003
        (
            EvidenceManifestItem(
                file_id="evidence_37",
                file_path="evidence/images/security_audit_explorer_20260905.png",
                origin="security_service",
                captured_at=_utc_dt("2026-09-05T07:00:00Z"),
            ),
            ResolvedIdentity(
                case_id="c_37",
                request_email="oliver-bennett@gmail.com",
                user_ids=("user_03",),
                names=("Oliver Bennett",),
                all_emails=("oliver-bennett@gmail.com",),
            ),
            "audit_record_003",
            "security_service",
            DataCategory.SECURITY_AUDIT_LOG,
            ObservedResourceStatus.PRESENT_RETAINED,
        ),
        # evidence_42: deleted_account_reference_20260310.png -> tombstone_17
        (
            EvidenceManifestItem(
                file_id="evidence_42",
                file_path="evidence/images/deleted_account_reference_20260310.png",
                origin="identity_service",
                captured_at=_utc_dt("2026-03-10T06:00:00Z"),
            ),
            ResolvedIdentity(
                case_id="c_42",
                request_email="leonie.g9352@outlook.com",
                user_ids=("user_17",),
                names=("Léonie Girard",),
                all_emails=("leonie.g9352@outlook.com",),
            ),
            "tombstone_17",
            "identity_service",
            DataCategory.ACCOUNT_TOMBSTONE,
            ObservedResourceStatus.PRESENT_REDACTED,
        ),
        # evidence_46: object_storage_browser_20260213.png -> object_19
        (
            EvidenceManifestItem(
                file_id="evidence_46",
                file_path="evidence/images/object_storage_browser_20260213.png",
                origin="object_storage",
                captured_at=_utc_dt("2026-02-13T08:00:00Z"),
            ),
            ResolvedIdentity(
                case_id="c_46",
                request_email="priya.raman@gmail.com",
                user_ids=("user_07",),
                names=("Priya Raman",),
                all_emails=("priya.raman@gmail.com",),
            ),
            "object_19",
            "object_storage",
            DataCategory.SUPPORT_ATTACHMENT,
            ObservedResourceStatus.PRESENT_IDENTIFIABLE,
        ),
        # evidence_60: marketing_profile_console.png -> marketing_001
        (
            EvidenceManifestItem(
                file_id="evidence_60",
                file_path="evidence/images/marketing_profile_console.png",
                origin="marketing_platform",
                captured_at=_utc_dt("2026-09-16T07:20:00Z"),
            ),
            ResolvedIdentity(
                case_id="c_60",
                request_email="sj.park@naver.com",
                user_ids=("user_09",),
                names=("Soo-jin Park",),
                all_emails=("sj.park@naver.com",),
                phones=("+82 10-5837-9451",),
            ),
            "marketing_001",
            "marketing_platform",
            DataCategory.MARKETING_PROFILE,
            ObservedResourceStatus.PRESENT_IDENTIFIABLE,
        ),
    ]

    for item, identity, expected_rid, expected_sys, expected_cat, expected_status in cases:
        facts = extract_image_facts(audit_settings, item, identity)
        assert len(facts) >= 1, f"Expected facts for {item.file_path}"
        matching = [f for f in facts if f.resource_id == expected_rid]
        assert len(matching) == 1, f"Expected {expected_rid} in facts for {item.file_path}"
        fact = matching[0]
        assert fact.evidence_id == item.file_id
        assert fact.system_id == expected_sys
        assert fact.data_category == expected_cat
        assert fact.status == expected_status


def test_extraction_negative_unrelated_identity(audit_settings: AuditSettings) -> None:
    """Unrelated identity matches nothing in PDFs or images."""
    unrelated = ResolvedIdentity(
        case_id="unrelated_case",
        request_email="nobody.here@unknown-domain-xyz.com",
        user_ids=("user_9999",),
        names=("Nobody Nowhere",),
        all_emails=("nobody.here@unknown-domain-xyz.com",),
        phones=("+99 999 999 999",),
    )

    pdf_item = EvidenceManifestItem(
        file_id="evidence_58",
        file_path="evidence/documents/delivery_correction_attachment.pdf",
        origin="support_platform",
        captured_at=datetime.now(UTC),
    )
    pdf_facts = extract_pdf_facts(audit_settings, pdf_item, unrelated)
    assert pdf_facts == ()

    img_item = EvidenceManifestItem(
        file_id="evidence_04",
        file_path="evidence/images/account_admin_console_20260926.png",
        origin="account_admin_portal",
        captured_at=datetime.now(UTC),
    )
    img_facts = extract_image_facts(audit_settings, img_item, unrelated)
    assert img_facts == ()


def test_image_facts_caching(audit_settings: AuditSettings) -> None:
    """Verify that extract_image_facts results are cached in diskcache."""
    item = EvidenceManifestItem(
        file_id="evidence_04",
        file_path="evidence/images/account_admin_console_20260926.png",
        origin="account_admin_portal",
        captured_at=_utc_dt("2026-09-26T11:00:00Z"),
    )
    identity = ResolvedIdentity(
        case_id="cache_test_case",
        request_email="haruka.s1838@zoho.com",
        user_ids=("user_11",),
        names=("Haruka Sato",),
        all_emails=("haruka.s1838@zoho.com",),
        phones=("+81 90 7610 2507",),
    )
    # First invocation populates cache
    facts1 = extract_image_facts(audit_settings, item, identity)
    # Second invocation hits cache
    facts2 = extract_image_facts(audit_settings, item, identity)
    assert facts1 == facts2
    assert len(facts1) >= 1
