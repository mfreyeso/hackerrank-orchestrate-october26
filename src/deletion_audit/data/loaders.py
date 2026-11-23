"""Polars-based dataset CSV loaders with strict Pydantic validation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import polars as pl

from deletion_audit.config import AuditSettings
from deletion_audit.models import (
    Case,
    DeletionRule,
    EvidenceManifestItem,
    SystemActivityRow,
    UserAuditLogEntry,
    UserIdentityRow,
)


@dataclass(frozen=True)
class DatasetBundle:
    """In-memory typed representation of all participant-facing CSV inputs."""

    cases: tuple[Case, ...]
    identities: tuple[UserIdentityRow, ...]
    audit_log: tuple[UserAuditLogEntry, ...]
    activities: tuple[SystemActivityRow, ...]
    rules: tuple[DeletionRule, ...]
    manifest: tuple[EvidenceManifestItem, ...]


def load_cases(settings: AuditSettings, split: Literal["sample", "full"] = "sample") -> tuple[Case, ...]:
    """Load deletion request cases using polars."""
    filename = "sample_deletion_requests.csv" if split == "sample" else "deletion_requests.csv"
    path = settings.resolve_dataset_file(filename)
    df = pl.read_csv(path)
    return tuple(Case.model_validate(row) for row in df.iter_rows(named=True))


def load_identities(settings: AuditSettings) -> tuple[UserIdentityRow, ...]:
    """Load current user identities snapshot."""
    path = settings.resolve_dataset_file("user_identities.csv")
    df = pl.read_csv(path)
    return tuple(UserIdentityRow.model_validate(row) for row in df.iter_rows(named=True))


def load_audit_log(settings: AuditSettings) -> tuple[UserAuditLogEntry, ...]:
    """Load historical user identity audit log."""
    path = settings.resolve_dataset_file("user_audit_log.csv")
    df = pl.read_csv(path)
    return tuple(UserAuditLogEntry.model_validate(row) for row in df.iter_rows(named=True))


def load_system_activity(settings: AuditSettings) -> tuple[SystemActivityRow, ...]:
    """Load global system activity stream."""
    path = settings.resolve_dataset_file("system_activity.csv")
    df = pl.read_csv(path)
    return tuple(SystemActivityRow.model_validate(row) for row in df.iter_rows(named=True))


def load_deletion_rules(settings: AuditSettings) -> tuple[DeletionRule, ...]:
    """Load policy rules from deletion_rules.csv."""
    path = settings.resolve_dataset_file("deletion_rules.csv")
    df = pl.read_csv(path)
    return tuple(DeletionRule.model_validate(row) for row in df.iter_rows(named=True))


def load_evidence_manifest(settings: AuditSettings) -> tuple[EvidenceManifestItem, ...]:
    """Load evidence_files.csv manifest."""
    path = settings.resolve_dataset_file("evidence_files.csv")
    df = pl.read_csv(path)
    return tuple(EvidenceManifestItem.model_validate(row) for row in df.iter_rows(named=True))


def load_dataset_bundle(
    settings: AuditSettings,
    split: Literal["sample", "full"] = "sample",
) -> DatasetBundle:
    """Load all dataset CSVs for the requested split."""
    return DatasetBundle(
        cases=load_cases(settings, split=split),
        identities=load_identities(settings),
        audit_log=load_audit_log(settings),
        activities=load_system_activity(settings),
        rules=load_deletion_rules(settings),
        manifest=load_evidence_manifest(settings),
    )
