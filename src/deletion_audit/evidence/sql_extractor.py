"""SQL snapshot extractor using SandboxedSQLSnapshot (in-memory sqlite3)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import orjson

from deletion_audit.config import AuditSettings
from deletion_audit.data.sql_sandbox import SandboxedSQLSnapshot
from deletion_audit.models import (
    DataCategory,
    EvidenceFact,
    EvidenceManifestItem,
    ObservedResourceStatus,
    ResolvedIdentity,
)


@lru_cache(maxsize=128)
def _load_sql_tables_cached(path: Path) -> tuple[tuple[str, tuple[dict[str, Any], ...]], ...]:
    snapshot = SandboxedSQLSnapshot.from_path(path)
    try:
        tables = snapshot.list_tables()
        result: list[tuple[str, tuple[dict[str, Any], ...]]] = []
        for table in tables:
            if table == "snapshot_scope":
                continue
            rows = tuple(snapshot.query(f'SELECT * FROM "{table}"'))
            result.append((table, rows))
        return tuple(result)
    finally:
        snapshot.close()


def _infer_category_from_collection(collection: str, resource_id: str) -> DataCategory:
    col = collection.lower()
    if "profile" in col and "analytics" not in col and "marketing" not in col:
        return DataCategory.USER_PROFILE
    if "search" in col:
        return DataCategory.SEARCH_INDEX_ENTRY
    if "analytics" in col:
        return DataCategory.ANALYTICS_PROFILE
    if "support" in col:
        return DataCategory.SUPPORT_MESSAGE
    if "export" in col:
        return DataCategory.USER_EXPORT
    if "connector" in col or "data_flow" in resource_id:
        return DataCategory.DATA_FLOW
    if "backup" in col or "backup_" in resource_id:
        return DataCategory.BACKUP_ARCHIVE
    if "security" in col or "audit_record" in resource_id:
        return DataCategory.SECURITY_AUDIT_LOG
    if "tombstone" in col or "deleted_customer" in col or "tombstone_" in resource_id:
        return DataCategory.ACCOUNT_TOMBSTONE
    return DataCategory.USER_PROFILE


def _infer_system_from_table(table_name: str, resource_id: str) -> str:
    t = table_name.lower()
    if "profile" in t or resource_id.startswith("account_"):
        return "account_service"
    if "search" in t or resource_id.startswith("search_"):
        return "search_service"
    if "analytics" in t or resource_id.startswith("analytics_"):
        return "analytics_platform"
    if "support" in t or resource_id.startswith("support_"):
        return "support_platform"
    if "export" in t or resource_id.startswith("export_"):
        return "export_service"
    if "connector" in t or resource_id.startswith("data_flow_"):
        return "integration_service"
    if "backup" in t or resource_id.startswith("backup_"):
        return "backup_service"
    if "security" in t or resource_id.startswith("audit_record_"):
        return "security_service"
    return "account_service"


def _row_matches_identity(
    row: dict[str, Any],
    identity: ResolvedIdentity,
    known_resource_ids: set[str],
) -> tuple[bool, tuple[str, ...]]:
    matched: list[str] = []
    res_id = str(row.get("resource_id") or "")
    if res_id and res_id in known_resource_ids:
        matched.append(res_id)

    for val in row.values():
        if val is None:
            continue
        sval = str(val)
        if identity.matches_value(sval):
            matched.append(sval)
        elif sval.startswith("{") and sval.endswith("}"):
            try:
                parsed = orjson.loads(sval)
                if isinstance(parsed, dict):
                    for k, inner in parsed.items():
                        if isinstance(inner, str) and identity.matches_value(inner):
                            matched.append(inner)
                        elif k == "document" and isinstance(inner, dict):
                            for doc_val in inner.values():
                                if isinstance(doc_val, str) and identity.matches_value(doc_val):
                                    matched.append(doc_val)
            except orjson.JSONDecodeError:
                pass

    return (len(matched) > 0, tuple(sorted(set(matched))))


def _determine_status_from_payload(
    category: DataCategory,
    payload: dict[str, Any],
) -> ObservedResourceStatus:
    if category == DataCategory.DATA_FLOW:
        enabled = payload.get("enabled")
        is_enabled = enabled in (True, 1, "1", "true", "TRUE")
        return ObservedResourceStatus.FLOW_ACTIVE if is_enabled else ObservedResourceStatus.FLOW_DISABLED

    if category == DataCategory.BACKUP_ARCHIVE:
        restore_allowed = payload.get("restore_allowed")
        is_allowed = restore_allowed in (True, 1, "1", "true", "TRUE")
        return (
            ObservedResourceStatus.RESTORE_ACTIVE
            if is_allowed
            else ObservedResourceStatus.RESTORE_BLOCKED
        )

    if category == DataCategory.SECURITY_AUDIT_LOG:
        return ObservedResourceStatus.PRESENT_RETAINED

    if category == DataCategory.ANALYTICS_PROFILE:
        pii_fields = ("user_id", "customer_reference", "email", "phone", "email_hash")
        has_pii = any(payload.get(f) not in (None, "", "null") for f in pii_fields)
        return (
            ObservedResourceStatus.PRESENT_IDENTIFIABLE
            if has_pii
            else ObservedResourceStatus.PRESENT_ANONYMIZED
        )

    if category == DataCategory.SUPPORT_MESSAGE:
        msg = str(payload.get("message_text") or payload.get("message_excerpt") or "")
        req_email = payload.get("requester_email")
        req_name = payload.get("requester_name")
        req_phone = payload.get("requester_phone")
        if msg == "[REDACTED]" or (
            req_email is None and req_name is None and req_phone is None and "@" not in msg
        ):
            return ObservedResourceStatus.PRESENT_REDACTED
        return ObservedResourceStatus.PRESENT_IDENTIFIABLE

    if category == DataCategory.ACCOUNT_TOMBSTONE:
        direct_pii = ("name", "full_name", "email", "phone", "email_hash")
        has_pii = any(payload.get(f) not in (None, "", "null") for f in direct_pii)
        return (
            ObservedResourceStatus.PRESENT_IDENTIFIABLE
            if has_pii
            else ObservedResourceStatus.PRESENT_REDACTED
        )

    return ObservedResourceStatus.PRESENT_IDENTIFIABLE


def extract_sql_snapshot_facts(
    settings: AuditSettings,
    item: EvidenceManifestItem,
    identity: ResolvedIdentity,
    known_resource_ids: set[str] | None = None,
) -> tuple[EvidenceFact, ...]:
    """Load SQL snapshot into SandboxedSQLSnapshot and extract matching EvidenceFacts."""
    known_ids = known_resource_ids or set()
    path = settings.resolve_dataset_file(item.file_path)
    table_rows = _load_sql_tables_cached(path)
    facts: list[EvidenceFact] = []
    present_account_ids: set[str] = set()

    tables = [t for t, _ in table_rows]
    for table, rows in table_rows:
        is_replica = "replica" in table.lower()
        for row in rows:
            res_id = str(row.get("resource_id") or "")
            if res_id.startswith("account_"):
                present_account_ids.add(res_id)

            matched, matched_vals = _row_matches_identity(row, identity, known_ids)
            if not matched:
                continue

            if "record_json" in row and isinstance(row["record_json"], str):
                payload = orjson.loads(row["record_json"])
                system_id = str(row.get("origin_system") or _infer_system_from_table(table, res_id))
                collection = str(row.get("collection_name") or table)
                category = _infer_category_from_collection(collection, res_id)
            else:
                payload = row
                system_id = _infer_system_from_table(table, res_id)
                category = _infer_category_from_collection(table, res_id)

            status = _determine_status_from_payload(category, payload)
            facts.append(
                EvidenceFact(
                    evidence_id=item.file_id,
                    captured_at=item.captured_at,
                    system_id=system_id,
                    resource_id=res_id,
                    data_category=category,
                    status=status,
                    matched_identifiers=matched_vals,
                    is_replica_only=is_replica,
                    notes=f"SQL table {table}",
                )
            )

    # If a known account_* resource for this case is absent from all profile tables in an
    # account/inventory snapshot, emit an ABSENT fact for that account_id.
    has_profile_table = any("profile" in t.lower() or "customer_data" in t.lower() for t in tables)
    if has_profile_table:
        for res_id in sorted(known_ids):
            if res_id.startswith("account_") and res_id not in present_account_ids:
                facts.append(
                    EvidenceFact(
                        evidence_id=item.file_id,
                        captured_at=item.captured_at,
                        system_id="account_service",
                        resource_id=res_id,
                        data_category=DataCategory.USER_PROFILE,
                        status=ObservedResourceStatus.ABSENT,
                        matched_identifiers=(res_id,),
                        notes="Account profile absent from SQL snapshot",
                    )
                )

    return tuple(facts)
