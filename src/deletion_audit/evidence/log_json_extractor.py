"""Deterministic + LLM-fallback extractors for JSON, TXT handover, and LOG evidence files."""

from __future__ import annotations

import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import orjson

from deletion_audit.config import AuditSettings
from deletion_audit.evidence.sql_extractor import (
    _determine_status_from_payload,
    _infer_category_from_collection,
    _infer_system_from_table,
)
from deletion_audit.models import (
    DataCategory,
    EvidenceFact,
    EvidenceManifestItem,
    ObservedResourceStatus,
    ResolvedIdentity,
)


@lru_cache(maxsize=128)
def _read_json_cached(path: Path) -> Any:
    return orjson.loads(path.read_bytes())


@lru_cache(maxsize=128)
def _read_lines_cached(path: Path) -> tuple[str, ...]:
    return tuple(path.read_text(encoding="utf-8").splitlines())


@lru_cache(maxsize=128)
def _parse_log_file_cached(
    path: Path,
) -> tuple[tuple[dict[str, str], ...], dict[str, frozenset[str]]]:
    lines = _read_lines_cached(path)
    parsed_lines = tuple(_parse_log_line(line) for line in lines)
    trace_keys: dict[str, set[str]] = {}
    for pf in parsed_lines:
        tr = pf.get("trace_id")
        if not tr:
            continue
        for key_field in (
            "lookup_key",
            "match_key",
            "subject_key",
            "subject_ref",
            "subject_reference",
            "scan_key",
            "correlation_key",
            "matched_value",
            "customer_email",
            "customer_reference",
            "requester_email",
            "owner_email",
            "email",
        ):
            val = pf.get(key_field)
            if val and val != "null":
                trace_keys.setdefault(tr, set()).add(val)
    frozen_traces = {k: frozenset(v) for k, v in trace_keys.items()}
    return parsed_lines, frozen_traces


_KV_PAIR_RE = re.compile(r'([a-zA-Z_][a-zA-Z0-9_]*)=("[^"]*"|\S+)')
_TRACE_BRACKET_RE = re.compile(r"\[(tr-[0-9a-zA-Z_-]+)\]")
_SYSLOG_RE = re.compile(r"^(\S+)\s+<\d+>\d+\s+\S+\s+(\S+)\s+(tr-[0-9a-zA-Z_-]+)")
_BRACKET_SERVICE_RE = re.compile(
    r"^(\S+)\s+\[[A-Z]+\]\s+\[([a-z0-9_]+)\]\s+\[(tr-[0-9a-zA-Z_-]+)\]\s+([a-z0-9_]+):"
)


def _infer_category_for_resource(
    system_id: str,
    collection_or_group: str,
    resource_id: str,
) -> DataCategory:
    """Accurately infer DataCategory prioritizing deterministic resource_id prefix and system_id."""
    rid = resource_id.lower()
    sid = system_id.lower()
    col = collection_or_group.lower()

    if rid.startswith("account_") or sid == "account_service":
        return DataCategory.USER_PROFILE
    if rid.startswith("analytics_") or sid == "analytics_platform":
        return DataCategory.ANALYTICS_PROFILE
    if rid.startswith("tombstone_") or sid == "identity_service":
        return DataCategory.ACCOUNT_TOMBSTONE
    if rid.startswith("data_flow_") or sid == "integration_service":
        return DataCategory.DATA_FLOW
    if rid.startswith("backup_") or sid == "backup_service":
        return DataCategory.BACKUP_ARCHIVE
    if rid.startswith("audit_record_") or sid == "security_service":
        return DataCategory.SECURITY_AUDIT_LOG
    if rid.startswith("search_") or sid == "search_service":
        return DataCategory.SEARCH_INDEX_ENTRY
    if rid.startswith("export_") or sid == "export_service":
        return DataCategory.USER_EXPORT
    if rid.startswith("support_") or sid == "support_platform":
        if "attachment" in col or "attachment" in rid:
            return DataCategory.SUPPORT_ATTACHMENT
        return DataCategory.SUPPORT_MESSAGE

    return _infer_category_from_collection(collection_or_group, resource_id)


def _dict_matches_identity(
    record: dict[str, Any],
    identity: ResolvedIdentity,
    known_resource_ids: set[str],
) -> tuple[bool, tuple[str, ...]]:
    matched: list[str] = []
    res_id = str(record.get("resource_id") or "")
    if res_id and res_id in known_resource_ids:
        matched.append(res_id)

    def _check_val(val: Any) -> None:
        if isinstance(val, str):
            if identity.matches_value(val):
                matched.append(val)
        elif isinstance(val, dict):
            for inner in val.values():
                _check_val(inner)
        elif isinstance(val, list):
            for elem in val:
                _check_val(elem)

    for _k, val in record.items():
        _check_val(val)

    return (len(matched) > 0, tuple(sorted(set(matched))))


def extract_json_facts(
    settings: AuditSettings,
    item: EvidenceManifestItem,
    identity: ResolvedIdentity,
    known_resource_ids: set[str] | None = None,
) -> tuple[EvidenceFact, ...]:
    """Deterministically parse JSON evidence files (bundles, service_exports, and collections)."""
    known_ids = known_resource_ids or set()
    path = settings.resolve_dataset_file(item.file_path)
    data = _read_json_cached(path)
    facts: list[EvidenceFact] = []
    present_account_ids: set[str] = set()

    # Format 1: records_assurance_snapshot_bundle ("snapshots": [...])
    if isinstance(data, dict) and isinstance(data.get("snapshots"), list):
        has_account_collection = False
        for snap in data["snapshots"]:
            if not isinstance(snap, dict):
                continue
            system_id = str(snap.get("data_store") or item.origin)
            collection = str(snap.get("collection") or "")
            if system_id == "account_service":
                has_account_collection = True
            snap_ts_str = str(snap.get("captured_at") or item.captured_at.isoformat())
            snap_ts = datetime.fromisoformat(snap_ts_str.replace("Z", "+00:00"))
            for rec in snap.get("records", []):
                if not isinstance(rec, dict):
                    continue
                res_id = str(rec.get("resource_id") or "")
                if res_id.startswith("account_"):
                    present_account_ids.add(res_id)
                matched, matched_vals = _dict_matches_identity(rec, identity, known_ids)
                if not matched:
                    continue
                category = _infer_category_for_resource(system_id, collection, res_id)
                status = _determine_status_from_payload(category, rec)
                facts.append(
                    EvidenceFact(
                        evidence_id=item.file_id,
                        captured_at=snap_ts,
                        system_id=system_id,
                        resource_id=res_id,
                        data_category=category,
                        status=status,
                        matched_identifiers=matched_vals,
                        notes=f"JSON snapshot {collection}",
                    )
                )
        if has_account_collection:
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
                            notes="Absent from JSON customer_profiles snapshot",
                        )
                    )
        return tuple(facts)

    # Format 2: service_resource_export ("service_exports": {...})
    if isinstance(data, dict) and isinstance(data.get("service_exports"), dict):
        svc_exports: dict[str, Any] = data["service_exports"]
        for system_id, group_dict in svc_exports.items():
            if not isinstance(group_dict, dict):
                continue
            for group_name, records in group_dict.items():
                if not isinstance(records, list):
                    continue
                for rec in records:
                    if not isinstance(rec, dict):
                        continue
                    res_id = str(rec.get("resource_id") or "")
                    matched, matched_vals = _dict_matches_identity(rec, identity, known_ids)
                    if not matched:
                        continue
                    category = _infer_category_for_resource(system_id, group_name, res_id)
                    if system_id == "account_service" and group_name == "profile_lookups":
                        status = (
                            ObservedResourceStatus.ABSENT
                            if rec.get("status_code") == 404 or rec.get("profile") is None
                            else ObservedResourceStatus.PRESENT_IDENTIFIABLE
                        )
                    else:
                        status = _determine_status_from_payload(category, rec)
                    facts.append(
                        EvidenceFact(
                            evidence_id=item.file_id,
                            captured_at=item.captured_at,
                            system_id=system_id,
                            resource_id=res_id,
                            data_category=category,
                            status=status,
                            matched_identifiers=matched_vals,
                            notes=f"service_resource_export {system_id}.{group_name}",
                        )
                    )
        return tuple(facts)

    # Format 3: top-level "records" list
    if isinstance(data, dict) and isinstance(data.get("records"), list):
        collection = str(data.get("collection") or item.origin)
        for rec in data["records"]:
            if not isinstance(rec, dict):
                continue
            res_id = str(rec.get("resource_id") or "")
            matched, matched_vals = _dict_matches_identity(rec, identity, known_ids)
            if not matched:
                continue
            system_id = _infer_system_from_table(collection, res_id)
            category = _infer_category_for_resource(system_id, collection, res_id)
            status = _determine_status_from_payload(category, rec)
            facts.append(
                EvidenceFact(
                    evidence_id=item.file_id,
                    captured_at=item.captured_at,
                    system_id=system_id,
                    resource_id=res_id,
                    data_category=category,
                    status=status,
                    matched_identifiers=matched_vals,
                    notes=f"JSON collection {collection}",
                )
            )
    return tuple(facts)


def extract_txt_handover_facts(
    settings: AuditSettings,
    item: EvidenceManifestItem,
    identity: ResolvedIdentity,
    known_resource_ids: set[str] | None = None,
) -> tuple[EvidenceFact, ...]:
    """Parse pipe-delimited shift handover text files (`customer_account_handover_*.txt`)."""
    known_ids = known_resource_ids or set()
    path = settings.resolve_dataset_file(item.file_path)
    lines = _read_lines_cached(path)
    facts: list[EvidenceFact] = []

    status_map: dict[str, ObservedResourceStatus] = {
        "NOT_FOUND": ObservedResourceStatus.ABSENT,
        "ABSENT": ObservedResourceStatus.ABSENT,
        "IDENTIFIABLE": ObservedResourceStatus.PRESENT_IDENTIFIABLE,
        "ANONYMIZED": ObservedResourceStatus.PRESENT_ANONYMIZED,
        "REDACTED": ObservedResourceStatus.PRESENT_REDACTED,
        "ACTIVE": ObservedResourceStatus.FLOW_ACTIVE,
        "DISABLED": ObservedResourceStatus.FLOW_DISABLED,
        "BLOCKED": ObservedResourceStatus.RESTORE_BLOCKED,
    }

    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("- ") or "|" not in stripped:
            continue
        parts = [p.strip() for p in stripped[2:].split("|")]
        if len(parts) != 6:
            continue
        ts_str, system_id, resource_id, cat_str, raw_status, identifier = parts
        if not (identity.matches_value(identifier) or resource_id in known_ids):
            continue
        try:
            category = DataCategory(cat_str)
        except ValueError:
            category = _infer_category_from_collection(cat_str, resource_id)

        if category == DataCategory.BACKUP_ARCHIVE and raw_status == "ACTIVE":
            norm_status = ObservedResourceStatus.RESTORE_ACTIVE
        elif category == DataCategory.SECURITY_AUDIT_LOG and raw_status == "FOUND":
            norm_status = ObservedResourceStatus.PRESENT_RETAINED
        elif raw_status == "FOUND":
            norm_status = ObservedResourceStatus.PRESENT_IDENTIFIABLE
        else:
            norm_status = status_map.get(raw_status, ObservedResourceStatus.PRESENT_IDENTIFIABLE)

        captured = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        facts.append(
            EvidenceFact(
                evidence_id=item.file_id,
                captured_at=captured,
                system_id=system_id,
                resource_id=resource_id,
                data_category=category,
                status=norm_status,
                matched_identifiers=(identifier,),
                notes="Shift handover text line",
            )
        )

    return tuple(facts)


def _parse_log_line(line: str) -> dict[str, str]:
    """Parse key=value, JSON-line, pipe-delimited, syslog, or bracketed log line into a flat string dict."""
    fields: dict[str, str] = {}
    stripped = line.strip()
    if not stripped:
        return fields

    if " | " in stripped:
        pipe_parts = [p.strip() for p in stripped.split(" | ")]
        if len(pipe_parts) >= 5 and pipe_parts[0].endswith("Z"):
            fields["timestamp"] = pipe_parts[0]
            fields["level"] = pipe_parts[1]
            fields["service"] = pipe_parts[2]
            fields["trace_id"] = pipe_parts[3]
            fields["event"] = pipe_parts[4]
            rest_kv = " ".join(pipe_parts[5:]).replace('\\"', '"')
            for k, raw_v in _KV_PAIR_RE.findall(rest_kv):
                fields[k] = raw_v.strip('"')
            return fields

    parts = stripped.split(" ", 1)
    if len(parts) == 2 and parts[0].endswith("Z"):
        fields["timestamp"] = parts[0]
        rest = parts[1].strip()
        if rest.startswith("{") and rest.endswith("}"):
            try:
                parsed = orjson.loads(rest)
                if isinstance(parsed, dict):
                    for k, v in parsed.items():
                        fields[str(k)] = "" if v is None else str(v)
                    return fields
            except orjson.JSONDecodeError:
                pass

    m_sys = _SYSLOG_RE.match(stripped)
    if m_sys:
        fields["timestamp"] = m_sys.group(1)
        fields["service"] = m_sys.group(2)
        fields["trace_id"] = m_sys.group(3)

    m_brk = _BRACKET_SERVICE_RE.match(stripped)
    if m_brk:
        fields["timestamp"] = m_brk.group(1)
        fields["service"] = m_brk.group(2)
        fields["trace_id"] = m_brk.group(3)
        fields["event"] = m_brk.group(4)

    m_tr = _TRACE_BRACKET_RE.search(stripped)
    if m_tr and "trace_id" not in fields:
        fields["trace_id"] = m_tr.group(1)

    normalized = stripped.replace('\\"', '"')
    for k, raw_v in _KV_PAIR_RE.findall(normalized):
        v = raw_v.strip('"')
        fields[k] = v

    if "trace_id" not in fields and "requestId" in fields:
        fields["trace_id"] = fields["requestId"]
    if "service" not in fields and "function" in fields:
        fields["service"] = fields["function"]
    return fields


def extract_log_facts(
    settings: AuditSettings,
    item: EvidenceManifestItem,
    identity: ResolvedIdentity,
    known_resource_ids: set[str] | None = None,
) -> tuple[EvidenceFact, ...]:
    """Deterministically parse structured/semi-structured `.log` files by correlating trace_id."""
    known_ids = known_resource_ids or set()
    path = settings.resolve_dataset_file(item.file_path)
    parsed_lines, trace_keys = _parse_log_file_cached(path)

    facts: list[EvidenceFact] = []
    for pf in parsed_lines:
        res_id = pf.get("resource_id")
        if not res_id:
            continue
        tr = pf.get("trace_id", "")
        candidate_keys = set(trace_keys.get(tr, set()))
        for key_field in (
            "lookup_key",
            "match_key",
            "subject_key",
            "subject_ref",
            "subject_reference",
            "scan_key",
            "correlation_key",
            "matched_value",
            "customer_email",
            "customer_reference",
            "requester_email",
            "owner_email",
            "email",
        ):
            val = pf.get(key_field)
            if val and val != "null":
                candidate_keys.add(val)

        matched_ids = [k for k in candidate_keys if identity.matches_value(k)]
        if res_id in known_ids:
            matched_ids.append(res_id)
        if not matched_ids:
            continue

        event = pf.get("event", "")
        service = pf.get("service", "")
        if service in {"support_replica", "attachment_preview"}:
            system_id = "support_platform"
        elif service:
            system_id = service
        else:
            system_id = _infer_system_from_table("", res_id)

        # Ignore "*_started" events when a "*_completed" or scan result event follows
        if event.endswith("_started"):
            continue

        category = _infer_category_for_resource(system_id, "", res_id)
        status: ObservedResourceStatus | None = None
        shared_context = True

        if event == "record_lookup":
            system_id = pf.get("system") or system_id
            rec_type = pf.get("record_type", "")
            try:
                category = DataCategory(rec_type)
            except ValueError:
                category = _infer_category_for_resource(system_id, rec_type, res_id)
            res_val = pf.get("result", "").upper()
            if res_val in {"NOT_FOUND", "ABSENT"}:
                status = ObservedResourceStatus.ABSENT
            elif res_val == "FOUND":
                status = (
                    ObservedResourceStatus.PRESENT_RETAINED
                    if category == DataCategory.SECURITY_AUDIT_LOG
                    else ObservedResourceStatus.PRESENT_IDENTIFIABLE
                )
            elif res_val == "IDENTIFIABLE":
                status = ObservedResourceStatus.PRESENT_IDENTIFIABLE
            elif res_val == "ANONYMIZED":
                status = ObservedResourceStatus.PRESENT_ANONYMIZED
            elif res_val == "REDACTED":
                status = ObservedResourceStatus.PRESENT_REDACTED
            elif res_val == "ACTIVE":
                status = (
                    ObservedResourceStatus.RESTORE_ACTIVE
                    if category == DataCategory.BACKUP_ARCHIVE
                    else ObservedResourceStatus.FLOW_ACTIVE
                )
            elif res_val == "DISABLED":
                status = ObservedResourceStatus.FLOW_DISABLED
            elif res_val == "BLOCKED":
                status = ObservedResourceStatus.RESTORE_BLOCKED
        elif event == "profile_lookup_completed":
            status = (
                ObservedResourceStatus.ABSENT
                if pf.get("http_status") == "404" or pf.get("rows") == "0"
                else ObservedResourceStatus.PRESENT_IDENTIFIABLE
            )
        elif event == "index_query_completed":
            status = (
                ObservedResourceStatus.PRESENT_IDENTIFIABLE
                if pf.get("result") == "hit"
                else ObservedResourceStatus.ABSENT
            )
        elif event in {"message_pii_scan", "support_ticket_read_completed", "message_read"}:
            category = DataCategory.SUPPORT_MESSAGE
            if pf.get("message_text") == "[REDACTED]":
                has_pii = False
            else:
                has_pii = (
                    bool(pf.get("matched_value"))
                    or pf.get("requester_email", "null") != "null"
                    or pf.get("requester_name", "null") != "null"
                    or pf.get("requester_phone", "null") != "null"
                )
            status = (
                ObservedResourceStatus.PRESENT_IDENTIFIABLE
                if has_pii
                else ObservedResourceStatus.PRESENT_REDACTED
            )
        elif event == "attachment_pii_scan":
            category = DataCategory.SUPPORT_ATTACHMENT
            shared_context = False
            status = ObservedResourceStatus.PRESENT_IDENTIFIABLE
        elif event == "contact_query_completed":
            category = DataCategory.SUPPORT_ATTACHMENT
            shared_context = False
            status = (
                ObservedResourceStatus.PRESENT_IDENTIFIABLE
                if pf.get("rows", "0") != "0"
                else ObservedResourceStatus.ABSENT
            )
        elif event == "contact_lookup_completed":
            category = DataCategory.SECONDARY_IDENTIFIER
            status = (
                ObservedResourceStatus.PRESENT_IDENTIFIABLE
                if pf.get("rows", "0") != "0"
                else ObservedResourceStatus.ABSENT
            )
        elif event in {"export_metadata_read_completed", "export_download_check_completed"}:
            category = DataCategory.USER_EXPORT
            is_avail = (
                pf.get("available") == "true"
                or pf.get("downloadable") == "true"
                or pf.get("http_status") == "200"
            )
            status = (
                ObservedResourceStatus.PRESENT_IDENTIFIABLE
                if is_avail
                else ObservedResourceStatus.ABSENT
            )
        elif event in {
            "analytics_identity_scan",
            "analytics_profile_read_completed",
            "analytics_profile_read",
        }:
            category = DataCategory.ANALYTICS_PROFILE
            has_pii = (
                pf.get("direct_identifiers", "0") not in {"0", ""}
                or bool(pf.get("matched_value"))
                or pf.get("email", "null") != "null"
                or pf.get("phone", "null") != "null"
                or pf.get("email_hash", "null") != "null"
            )
            status = (
                ObservedResourceStatus.PRESENT_IDENTIFIABLE
                if has_pii
                else ObservedResourceStatus.PRESENT_ANONYMIZED
            )
        elif event == "audit_record_read_completed":
            category = DataCategory.SECURITY_AUDIT_LOG
            status = ObservedResourceStatus.PRESENT_RETAINED
        elif event in {"restore_candidate_evaluated", "restore_policy_read_completed"}:
            category = DataCategory.BACKUP_ARCHIVE
            is_risk = pf.get("eligible") == "true" or pf.get("restore_allowed") == "true"
            status = (
                ObservedResourceStatus.RESTORE_ACTIVE
                if is_risk
                else ObservedResourceStatus.RESTORE_BLOCKED
            )
        elif event == "restore_authorization_completed":
            category = DataCategory.BACKUP_ARCHIVE
            status = (
                ObservedResourceStatus.RESTORE_BLOCKED
                if pf.get("decision") in {"deny", "blocked"}
                else ObservedResourceStatus.RESTORE_ACTIVE
            )
        elif event == "deletion_marker_check":
            category = DataCategory.ACCOUNT_TOMBSTONE
            has_pii = pf.get("direct_identifiers", "0") not in {"0", ""} or bool(
                pf.get("matched_value")
            )
            status = (
                ObservedResourceStatus.PRESENT_IDENTIFIABLE
                if has_pii
                else ObservedResourceStatus.PRESENT_REDACTED
            )
        elif event in {
            "connector_heartbeat",
            "connector_config_loaded",
            "connector_config_read_completed",
        }:
            category = DataCategory.DATA_FLOW
            status = (
                ObservedResourceStatus.FLOW_ACTIVE
                if pf.get("enabled") == "true"
                else ObservedResourceStatus.FLOW_DISABLED
            )

        if status is not None:
            facts.append(
                EvidenceFact(
                    evidence_id=item.file_id,
                    captured_at=item.captured_at,
                    system_id=system_id,
                    resource_id=res_id,
                    data_category=category,
                    status=status,
                    matched_identifiers=tuple(sorted(set(matched_ids))),
                    shared_context=shared_context,
                    notes=f"Log event {event}",
                )
            )

    return tuple(facts)
