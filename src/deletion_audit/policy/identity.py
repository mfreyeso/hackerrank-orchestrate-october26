"""Deterministic identity resolution across current snapshot and historical audit logs."""

from __future__ import annotations

import hashlib

from deletion_audit.models import (
    Case,
    ResolvedIdentity,
    UserAuditLogEntry,
    UserIdentityRow,
)


def _sha256_lower(value: str) -> str:
    return hashlib.sha256(value.strip().lower().encode("utf-8")).hexdigest()


def resolve_identity(
    case: Case,
    identities: tuple[UserIdentityRow, ...],
    audit_log: tuple[UserAuditLogEntry, ...],
) -> ResolvedIdentity:
    """Resolve current and historical identifiers for `case` as of `case.audit_at`."""
    req_email = case.email.strip()
    req_email_lower = req_email.lower()

    matched_user_ids: set[str] = set()

    # 1. Direct match in user_identities.csv
    for row in identities:
        if row.email.strip().lower() == req_email_lower:
            matched_user_ids.add(row.user_id)

    # 2. Match via historical email changes in user_audit_log.csv at or before audit_at
    eligible_audit_entries = [entry for entry in audit_log if entry.event_time <= case.audit_at]
    for entry in eligible_audit_entries:
        if entry.field_name == "email" and (
            entry.old_value.strip().lower() == req_email_lower
            or entry.new_value.strip().lower() == req_email_lower
        ):
            matched_user_ids.add(entry.user_id)

    names: set[str] = set()
    current_emails: set[str] = set()
    historical_emails: set[str] = set()
    phones: set[str] = set()
    email_hashes: set[str] = set()
    audit_ids: set[str] = set()

    for row in identities:
        if row.user_id in matched_user_ids:
            names.add(row.name.strip())
            current_emails.add(row.email.strip())
            phones.add(row.phone.strip())
            email_hashes.add(row.email_hash.strip().lower())
            email_hashes.add(_sha256_lower(row.email))

    for entry in eligible_audit_entries:
        if entry.user_id not in matched_user_ids:
            continue
        audit_ids.add(entry.audit_id)
        if entry.field_name == "email":
            for val in (entry.old_value.strip(), entry.new_value.strip()):
                if val:
                    if all(val.lower() != c.lower() for c in current_emails):
                        historical_emails.add(val)
                    email_hashes.add(_sha256_lower(val))
        elif entry.field_name == "phone":
            for val in (entry.old_value.strip(), entry.new_value.strip()):
                if val:
                    phones.add(val)
        elif entry.field_name == "email_hash":
            for val in (entry.old_value.strip().lower(), entry.new_value.strip().lower()):
                if val:
                    email_hashes.add(val)

    all_emails_set: set[str] = {req_email} | current_emails | historical_emails
    email_hashes.add(_sha256_lower(req_email))

    return ResolvedIdentity(
        case_id=case.case_id,
        request_email=req_email,
        user_ids=tuple(sorted(matched_user_ids)),
        names=tuple(sorted(names)),
        current_emails=tuple(sorted(current_emails)),
        historical_emails=tuple(sorted(historical_emails)),
        all_emails=tuple(sorted(all_emails_set)),
        phones=tuple(sorted(phones)),
        email_hashes=tuple(sorted(email_hashes)),
        audit_ids=tuple(sorted(audit_ids)),
    )
