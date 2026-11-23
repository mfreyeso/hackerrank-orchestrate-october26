"""Deterministic policy engine applying deletion_rules.csv to reconstructed resource states."""

from __future__ import annotations

from deletion_audit.models import (
    DataCategory,
    DeletionRule,
    ObservedResourceStatus,
    PolicyDecision,
    RequiredAction,
    ResourceState,
    StepOperation,
    StepState,
)


class PolicyEngine:
    """Evaluates ResourceState objects against deletion_rules.csv."""

    def __init__(self, rules: tuple[DeletionRule, ...]) -> None:
        self._rules = rules
        self._by_category: dict[DataCategory, DeletionRule] = {
            rule.data_category: rule for rule in rules
        }

    def required_action_for(
        self,
        category: DataCategory,
        *,
        shared_context: bool = True,
    ) -> RequiredAction:
        """Look up the required policy action for a given data category."""
        if category == DataCategory.DATA_FLOW:
            return RequiredAction.DELETE
        if category == DataCategory.SUPPORT_MESSAGE and not shared_context:
            return RequiredAction.DELETE
        rule = self._by_category.get(category)
        if rule is not None:
            return rule.required_action
        return RequiredAction.DELETE

    def evaluate(self, resource: ResourceState) -> PolicyDecision:
        """Evaluate one ResourceState and return a PolicyDecision."""
        category = resource.data_category
        action = self.required_action_for(category, shared_context=resource.shared_context)

        # 1. Active synchronization / integration data flows
        if category == DataCategory.DATA_FLOW:
            if resource.status == ObservedResourceStatus.FLOW_DISABLED:
                return PolicyDecision(
                    system_id=resource.system_id,
                    resource_id=resource.resource_id,
                    data_category=category,
                    required_action=action,
                    is_compliant=True,
                    evidence_id=resource.evidence_id,
                    verification_op=StepOperation.VERIFY_DATA_FLOW_DISABLED,
                    verification_state=StepState.DISABLED,
                )
            return PolicyDecision(
                system_id=resource.system_id,
                resource_id=resource.resource_id,
                data_category=category,
                required_action=action,
                is_compliant=False,
                evidence_id=resource.evidence_id,
                finding_op=StepOperation.REPORT_ACTIVE_DATA_FLOW,
                finding_state=StepState.ACTIVE,
                remediation_op=StepOperation.DISABLE_DATA_FLOW,
                remediation_state=StepState.DISABLED,
                verification_op=StepOperation.VERIFY_DATA_FLOW_DISABLED,
                verification_state=StepState.DISABLED,
            )

        # 2. Backup archives (retained if restore access is blocked)
        if category == DataCategory.BACKUP_ARCHIVE:
            if resource.status == ObservedResourceStatus.RESTORE_BLOCKED:
                return PolicyDecision(
                    system_id=resource.system_id,
                    resource_id=resource.resource_id,
                    data_category=category,
                    required_action=RequiredAction.RETAIN,
                    is_compliant=True,
                    evidence_id=resource.evidence_id,
                    verification_op=StepOperation.VERIFY_RESTORE_BLOCKED,
                    verification_state=StepState.BLOCKED,
                )
            return PolicyDecision(
                system_id=resource.system_id,
                resource_id=resource.resource_id,
                data_category=category,
                required_action=RequiredAction.RETAIN,
                is_compliant=False,
                evidence_id=resource.evidence_id,
                finding_op=StepOperation.REPORT_RESTORE_RISK,
                finding_state=StepState.ACTIVE,
                remediation_op=StepOperation.BLOCK_RESTORE,
                remediation_state=StepState.BLOCKED,
                verification_op=StepOperation.VERIFY_RESTORE_BLOCKED,
                verification_state=StepState.BLOCKED,
            )

        # 3. Categories requiring full deletion (USER_PROFILE, SEARCH_INDEX_ENTRY, etc.)
        if action == RequiredAction.DELETE:
            if resource.status == ObservedResourceStatus.ABSENT:
                return PolicyDecision(
                    system_id=resource.system_id,
                    resource_id=resource.resource_id,
                    data_category=category,
                    required_action=action,
                    is_compliant=True,
                    evidence_id=resource.evidence_id,
                    verification_op=StepOperation.VERIFY_RECORD_ABSENT,
                    verification_state=StepState.ABSENT,
                )
            return PolicyDecision(
                system_id=resource.system_id,
                resource_id=resource.resource_id,
                data_category=category,
                required_action=action,
                is_compliant=False,
                evidence_id=resource.evidence_id,
                finding_op=StepOperation.REPORT_REMAINING_RECORD,
                finding_state=StepState.PRESENT,
                remediation_op=StepOperation.DELETE_RECORD,
                remediation_state=StepState.ABSENT,
                verification_op=StepOperation.VERIFY_RECORD_ABSENT,
                verification_state=StepState.ABSENT,
            )

        # 4. Categories requiring redaction (SUPPORT_MESSAGE, EMAIL_DELIVERY_LOG, ACCOUNT_TOMBSTONE)
        if action == RequiredAction.REDACT:
            if resource.status == ObservedResourceStatus.PRESENT_REDACTED:
                return PolicyDecision(
                    system_id=resource.system_id,
                    resource_id=resource.resource_id,
                    data_category=category,
                    required_action=action,
                    is_compliant=True,
                    evidence_id=resource.evidence_id,
                    verification_op=StepOperation.VERIFY_RECORD_REDACTED,
                    verification_state=StepState.REDACTED,
                )
            return PolicyDecision(
                system_id=resource.system_id,
                resource_id=resource.resource_id,
                data_category=category,
                required_action=action,
                is_compliant=False,
                evidence_id=resource.evidence_id,
                finding_op=StepOperation.REPORT_EXPOSED_PII,
                finding_state=StepState.PRESENT,
                remediation_op=StepOperation.REDACT_RECORD,
                remediation_state=StepState.REDACTED,
                verification_op=StepOperation.VERIFY_RECORD_REDACTED,
                verification_state=StepState.REDACTED,
            )

        # 5. Categories requiring anonymization (ANALYTICS_PROFILE, PRODUCT_TELEMETRY)
        if action == RequiredAction.ANONYMIZE:
            if resource.status == ObservedResourceStatus.PRESENT_ANONYMIZED:
                return PolicyDecision(
                    system_id=resource.system_id,
                    resource_id=resource.resource_id,
                    data_category=category,
                    required_action=action,
                    is_compliant=True,
                    evidence_id=resource.evidence_id,
                    verification_op=StepOperation.VERIFY_RECORD_ANONYMIZED,
                    verification_state=StepState.ANONYMIZED,
                )
            return PolicyDecision(
                system_id=resource.system_id,
                resource_id=resource.resource_id,
                data_category=category,
                required_action=action,
                is_compliant=False,
                evidence_id=resource.evidence_id,
                finding_op=StepOperation.REPORT_EXPOSED_PII,
                finding_state=StepState.PRESENT,
                remediation_op=StepOperation.ANONYMIZE_RECORD,
                remediation_state=StepState.ANONYMIZED,
                verification_op=StepOperation.VERIFY_RECORD_ANONYMIZED,
                verification_state=StepState.ANONYMIZED,
            )

        # 6. Categories requiring retention (SECURITY_AUDIT_LOG, LEGAL_HOLD_RECORD)
        is_present = resource.status in {
            ObservedResourceStatus.PRESENT_RETAINED,
            ObservedResourceStatus.PRESENT_IDENTIFIABLE,
        }
        return PolicyDecision(
            system_id=resource.system_id,
            resource_id=resource.resource_id,
            data_category=category,
            required_action=RequiredAction.RETAIN,
            is_compliant=is_present,
            evidence_id=resource.evidence_id,
            verification_op=StepOperation.VERIFY_RECORD_PRESENT,
            verification_state=StepState.PRESENT,
        )

    def evaluate_all(self, resources: tuple[ResourceState, ...]) -> tuple[PolicyDecision, ...]:
        """Evaluate all reconstructed resource states for a case."""
        return tuple(self.evaluate(r) for r in resources)
