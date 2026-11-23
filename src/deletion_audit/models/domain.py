"""Typed domain models for the deletion audit agent."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ReportedStatus(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIALLY_COMPLETE = "PARTIALLY_COMPLETE"
    NOT_STARTED = "NOT_STARTED"


class DeletionStatus(StrEnum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class DataCategory(StrEnum):
    USER_PROFILE = "USER_PROFILE"
    SECONDARY_IDENTIFIER = "SECONDARY_IDENTIFIER"
    SEARCH_INDEX_ENTRY = "SEARCH_INDEX_ENTRY"
    CACHE_ENTRY = "CACHE_ENTRY"
    SUPPORT_MESSAGE = "SUPPORT_MESSAGE"
    SUPPORT_ATTACHMENT = "SUPPORT_ATTACHMENT"
    ANALYTICS_PROFILE = "ANALYTICS_PROFILE"
    PRODUCT_TELEMETRY = "PRODUCT_TELEMETRY"
    USER_EXPORT = "USER_EXPORT"
    MARKETING_PROFILE = "MARKETING_PROFILE"
    EMAIL_DELIVERY_LOG = "EMAIL_DELIVERY_LOG"
    SECURITY_AUDIT_LOG = "SECURITY_AUDIT_LOG"
    LEGAL_HOLD_RECORD = "LEGAL_HOLD_RECORD"
    BACKUP_ARCHIVE = "BACKUP_ARCHIVE"
    ACCOUNT_TOMBSTONE = "ACCOUNT_TOMBSTONE"
    DATA_FLOW = "DATA_FLOW"


class RequiredAction(StrEnum):
    DELETE = "DELETE"
    REDACT = "REDACT"
    ANONYMIZE = "ANONYMIZE"
    RETAIN = "RETAIN"


class StepPhase(StrEnum):
    FINDING = "FINDING"
    REMEDIATION = "REMEDIATION"
    VERIFICATION = "VERIFICATION"


class StepOperation(StrEnum):
    # Findings
    REPORT_REMAINING_RECORD = "REPORT_REMAINING_RECORD"
    REPORT_EXPOSED_PII = "REPORT_EXPOSED_PII"
    REPORT_ACTIVE_DATA_FLOW = "REPORT_ACTIVE_DATA_FLOW"
    REPORT_RESTORE_RISK = "REPORT_RESTORE_RISK"
    # Remediation
    DISABLE_DATA_FLOW = "DISABLE_DATA_FLOW"
    BLOCK_RESTORE = "BLOCK_RESTORE"
    DELETE_RECORD = "DELETE_RECORD"
    REDACT_RECORD = "REDACT_RECORD"
    ANONYMIZE_RECORD = "ANONYMIZE_RECORD"
    # Verification
    VERIFY_RECORD_ABSENT = "VERIFY_RECORD_ABSENT"
    VERIFY_RECORD_PRESENT = "VERIFY_RECORD_PRESENT"
    VERIFY_RECORD_REDACTED = "VERIFY_RECORD_REDACTED"
    VERIFY_RECORD_ANONYMIZED = "VERIFY_RECORD_ANONYMIZED"
    VERIFY_DATA_FLOW_DISABLED = "VERIFY_DATA_FLOW_DISABLED"
    VERIFY_RESTORE_BLOCKED = "VERIFY_RESTORE_BLOCKED"


class StepState(StrEnum):
    PRESENT = "PRESENT"
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    BLOCKED = "BLOCKED"
    ABSENT = "ABSENT"
    REDACTED = "REDACTED"
    ANONYMIZED = "ANONYMIZED"


PHASE_ORDER: tuple[StepPhase, ...] = (
    StepPhase.FINDING,
    StepPhase.REMEDIATION,
    StepPhase.VERIFICATION,
)

OPERATION_ORDER: tuple[StepOperation, ...] = (
    StepOperation.REPORT_REMAINING_RECORD,
    StepOperation.REPORT_EXPOSED_PII,
    StepOperation.REPORT_ACTIVE_DATA_FLOW,
    StepOperation.REPORT_RESTORE_RISK,
    StepOperation.DISABLE_DATA_FLOW,
    StepOperation.BLOCK_RESTORE,
    StepOperation.DELETE_RECORD,
    StepOperation.REDACT_RECORD,
    StepOperation.ANONYMIZE_RECORD,
    StepOperation.VERIFY_RECORD_ABSENT,
    StepOperation.VERIFY_RECORD_PRESENT,
    StepOperation.VERIFY_RECORD_REDACTED,
    StepOperation.VERIFY_RECORD_ANONYMIZED,
    StepOperation.VERIFY_DATA_FLOW_DISABLED,
    StepOperation.VERIFY_RESTORE_BLOCKED,
)

ALLOWED_TRIPLES: frozenset[tuple[StepPhase, StepOperation, StepState]] = frozenset(
    {
        (StepPhase.FINDING, StepOperation.REPORT_REMAINING_RECORD, StepState.PRESENT),
        (StepPhase.FINDING, StepOperation.REPORT_EXPOSED_PII, StepState.PRESENT),
        (StepPhase.FINDING, StepOperation.REPORT_ACTIVE_DATA_FLOW, StepState.ACTIVE),
        (StepPhase.FINDING, StepOperation.REPORT_RESTORE_RISK, StepState.ACTIVE),
        (StepPhase.REMEDIATION, StepOperation.DISABLE_DATA_FLOW, StepState.DISABLED),
        (StepPhase.REMEDIATION, StepOperation.BLOCK_RESTORE, StepState.BLOCKED),
        (StepPhase.REMEDIATION, StepOperation.DELETE_RECORD, StepState.ABSENT),
        (StepPhase.REMEDIATION, StepOperation.REDACT_RECORD, StepState.REDACTED),
        (StepPhase.REMEDIATION, StepOperation.ANONYMIZE_RECORD, StepState.ANONYMIZED),
        (StepPhase.VERIFICATION, StepOperation.VERIFY_RECORD_ABSENT, StepState.ABSENT),
        (StepPhase.VERIFICATION, StepOperation.VERIFY_RECORD_PRESENT, StepState.PRESENT),
        (StepPhase.VERIFICATION, StepOperation.VERIFY_RECORD_REDACTED, StepState.REDACTED),
        (StepPhase.VERIFICATION, StepOperation.VERIFY_RECORD_ANONYMIZED, StepState.ANONYMIZED),
        (StepPhase.VERIFICATION, StepOperation.VERIFY_DATA_FLOW_DISABLED, StepState.DISABLED),
        (StepPhase.VERIFICATION, StepOperation.VERIFY_RESTORE_BLOCKED, StepState.BLOCKED),
    }
)


class Case(BaseModel):
    """One row from deletion_requests.csv or sample_deletion_requests.csv."""

    model_config = ConfigDict(frozen=True)

    case_id: str
    email: str
    requested_at: datetime
    reported_status: ReportedStatus
    reported_at: datetime
    audit_at: datetime
    request_text: str


class UserIdentityRow(BaseModel):
    """One row from user_identities.csv."""

    model_config = ConfigDict(frozen=True)

    user_id: str
    name: str
    email: str
    phone: str
    email_hash: str
    updated_at: datetime


class UserAuditLogEntry(BaseModel):
    """One row from user_audit_log.csv."""

    model_config = ConfigDict(frozen=True)

    audit_id: str
    user_id: str
    event_time: datetime
    field_name: str
    old_value: str
    new_value: str


class ResolvedIdentity(BaseModel):
    """Resolved current and historical identifiers for a case subject as of audit_at."""

    model_config = ConfigDict(frozen=True)

    case_id: str
    request_email: str
    user_ids: tuple[str, ...] = ()
    names: tuple[str, ...] = ()
    current_emails: tuple[str, ...] = ()
    historical_emails: tuple[str, ...] = ()
    all_emails: tuple[str, ...] = ()
    phones: tuple[str, ...] = ()
    email_hashes: tuple[str, ...] = ()
    audit_ids: tuple[str, ...] = ()

    def matches_value(self, value: str | None) -> bool:
        """Check whether a candidate string matches any resolved identifier."""
        if not value:
            return False
        norm = value.strip()
        norm_lower = norm.lower()
        if norm in self.user_ids:
            return True
        if any(norm_lower == e.lower() for e in self.all_emails):
            return True
        if norm in self.phones:
            return True
        if any(norm_lower == h.lower() for h in self.email_hashes):
            return True
        return any(norm_lower == n.lower() for n in self.names)


class SystemActivityRow(BaseModel):
    """One row from system_activity.csv."""

    model_config = ConfigDict(frozen=True)

    activity_id: str
    event_time: datetime
    event_type: str
    source_system: str
    target_system: str
    resource_id: str
    reported_result: str
    details: str


class DeletionRule(BaseModel):
    """One row from deletion_rules.csv."""

    model_config = ConfigDict(frozen=True)

    rule_id: str
    data_category: DataCategory
    condition: str
    required_action: RequiredAction


class EvidenceManifestItem(BaseModel):
    """One row from evidence_files.csv."""

    model_config = ConfigDict(frozen=True)

    file_id: str
    file_path: str
    origin: str
    captured_at: datetime


class IntentClassification(BaseModel):
    """Structured output for classifying request_text intent."""

    model_config = ConfigDict(frozen=True)

    authorizes_deletion: bool
    intent_category: str = Field(default="DELETION")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    rationale: str = Field(default="")


class ObservedResourceStatus(StrEnum):
    """Normalized state of a resource observed in evidence."""

    PRESENT_IDENTIFIABLE = "PRESENT_IDENTIFIABLE"
    PRESENT_REDACTED = "PRESENT_REDACTED"
    PRESENT_ANONYMIZED = "PRESENT_ANONYMIZED"
    PRESENT_RETAINED = "PRESENT_RETAINED"
    ABSENT = "ABSENT"
    FLOW_ACTIVE = "FLOW_ACTIVE"
    FLOW_DISABLED = "FLOW_DISABLED"
    RESTORE_ACTIVE = "RESTORE_ACTIVE"
    RESTORE_BLOCKED = "RESTORE_BLOCKED"


class EvidenceFact(BaseModel):
    """Structured fact extracted from an evidence file or activity stream."""

    model_config = ConfigDict(frozen=True)

    evidence_id: str
    captured_at: datetime
    system_id: str
    resource_id: str
    data_category: DataCategory
    status: ObservedResourceStatus
    matched_identifiers: tuple[str, ...] = ()
    is_claim_only: bool = False
    is_replica_only: bool = False
    shared_context: bool = True
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    notes: str = ""


class ResourceState(BaseModel):
    """Reconstructed point-in-time state of a single (system_id, resource_id) at audit_at."""

    model_config = ConfigDict(frozen=True)

    system_id: str
    resource_id: str
    data_category: DataCategory
    status: ObservedResourceStatus
    evidence_id: str
    observed_at: datetime
    shared_context: bool = True
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class PolicyDecision(BaseModel):
    """Policy engine evaluation of a single ResourceState against deletion_rules.csv."""

    model_config = ConfigDict(frozen=True)

    system_id: str
    resource_id: str
    data_category: DataCategory
    required_action: RequiredAction
    is_compliant: bool
    evidence_id: str
    finding_op: StepOperation | None = None
    finding_state: StepState | None = None
    remediation_op: StepOperation | None = None
    remediation_state: StepState | None = None
    verification_op: StepOperation | None = None
    verification_state: StepState | None = None


class Step(BaseModel):
    """One step in steps_json."""

    model_config = ConfigDict(frozen=True)

    step_no: int = Field(ge=1)
    phase: StepPhase
    system_id: str = Field(min_length=1)
    resource_id: str = Field(min_length=1)
    operation: StepOperation
    state: StepState
    evidence_id: str = Field(default="")

    @model_validator(mode="after")
    def _validate_triple(self) -> Step:
        triple = (self.phase, self.operation, self.state)
        if triple not in ALLOWED_TRIPLES:
            msg = f"Illegal (phase, operation, state) triple: {triple}"
            raise ValueError(msg)
        return self


class CaseResult(BaseModel):
    """Final audit verdict and ordered steps for one deletion request."""

    model_config = ConfigDict(frozen=True)

    case_id: str
    deletion_status: DeletionStatus
    steps: tuple[Step, ...] = ()

    @model_validator(mode="after")
    def _validate_status_and_steps(self) -> CaseResult:
        if self.deletion_status == DeletionStatus.NOT_APPLICABLE and len(self.steps) > 0:
            msg = "NOT_APPLICABLE cases must have empty steps"
            raise ValueError(msg)
        return self
