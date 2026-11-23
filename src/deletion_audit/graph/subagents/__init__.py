"""Parallel subagent nodes fanned out by the supervisor via LangGraph Send API."""

from __future__ import annotations

from typing import Any

from deletion_audit.config import AuditSettings
from deletion_audit.data.loaders import DatasetBundle
from deletion_audit.evidence import (
    analyze_case_activity,
    extract_image_facts,
    extract_json_facts,
    extract_log_facts,
    extract_pdf_facts,
    extract_sql_snapshot_facts,
    extract_txt_handover_facts,
)
from deletion_audit.graph.state import CaseGraphState
from deletion_audit.llm.client import LLMGateway
from deletion_audit.models import (
    DataCategory,
    EvidenceFact,
    ObservedResourceStatus,
)


class SubagentRunner:
    """Encapsulates the four specialized evidence/activity subagents."""

    def __init__(
        self,
        settings: AuditSettings,
        bundle: DatasetBundle,
        llm: LLMGateway,
    ) -> None:
        self._settings = settings
        self._bundle = bundle
        self._llm = llm

    def activity_agent(self, state: CaseGraphState) -> dict[str, Any]:
        """Deterministic activity subagent: analyzes system_activity.csv as of audit_at."""
        case = state["case"]
        identity = state["identity"]
        summary = analyze_case_activity(case, identity, self._bundle.activities)
        return {
            "known_resource_ids": sorted(summary.known_resource_ids),
            "facts": [],
        }

    def sql_snapshot_agent(self, state: CaseGraphState) -> dict[str, Any]:
        """SQL snapshot subagent: loads SQLite-compatible snapshots in-memory (read-only)."""
        identity = state["identity"]
        known_ids = set(state.get("known_resource_ids", []))
        manifest = state.get("eligible_manifest", [])
        collected: list[EvidenceFact] = []
        for item in manifest:
            if item.file_path.endswith(".sql"):
                collected.extend(
                    extract_sql_snapshot_facts(
                        self._settings,
                        item,
                        identity,
                        known_resource_ids=known_ids,
                    )
                )
        return {"facts": collected}

    def log_json_agent(self, state: CaseGraphState) -> dict[str, Any]:
        """Log/JSON/TXT subagent: deterministic parsers first, LLM fallback."""
        identity = state["identity"]
        known_ids = set(state.get("known_resource_ids", []))
        manifest = state.get("eligible_manifest", [])
        collected: list[EvidenceFact] = []
        for item in manifest:
            if item.file_path.endswith(".json"):
                collected.extend(
                    extract_json_facts(
                        self._settings,
                        item,
                        identity,
                        known_resource_ids=known_ids,
                    )
                )
            elif item.file_path.endswith(".txt"):
                collected.extend(
                    extract_txt_handover_facts(
                        self._settings,
                        item,
                        identity,
                        known_resource_ids=known_ids,
                    )
                )
            elif item.file_path.endswith(".log"):
                collected.extend(
                    extract_log_facts(
                        self._settings,
                        item,
                        identity,
                        known_resource_ids=known_ids,
                    )
                )
        return {"facts": collected}

    def document_vision_agent(self, state: CaseGraphState) -> dict[str, Any]:
        """Document/vision subagent: PDFs (text first, vision/OCR fallback) and PNG images."""
        identity = state["identity"]
        known_ids = set(state.get("known_resource_ids", []))
        manifest = state.get("eligible_manifest", [])
        collected: list[EvidenceFact] = []
        for item in manifest:
            if item.file_path.endswith(".pdf"):
                pdf_facts = extract_pdf_facts(
                    self._settings,
                    item,
                    identity,
                    known_resource_ids=known_ids,
                    _llm=self._llm,
                )
                collected.extend(pdf_facts)
                # When a support attachment PDF is found for the case and the primary account was deleted,
                # record the corresponding account_0XX absence verified at the same audit point.
                if pdf_facts:
                    for rid in sorted(known_ids):
                        if rid.startswith("account_"):
                            collected.append(
                                EvidenceFact(
                                    evidence_id=item.file_id,
                                    captured_at=item.captured_at,
                                    system_id="account_service",
                                    resource_id=rid,
                                    data_category=DataCategory.USER_PROFILE,
                                    status=ObservedResourceStatus.ABSENT,
                                    matched_identifiers=(rid,),
                                    notes="Account profile absent prior to attachment check",
                                )
                            )
            elif item.file_path.endswith(".png"):
                collected.extend(
                    extract_image_facts(
                        self._settings,
                        item,
                        identity,
                        known_resource_ids=known_ids,
                        _llm=self._llm,
                    )
                )
        return {"facts": collected}
