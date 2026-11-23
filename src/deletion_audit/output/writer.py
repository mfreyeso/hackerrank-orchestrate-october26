"""Deterministic output.csv writer using orjson for steps_json serialization."""

from __future__ import annotations

import csv
from collections.abc import Sequence
from pathlib import Path

import orjson

from deletion_audit.models import CaseResult, DeletionStatus


def serialize_steps_json(result: CaseResult) -> str:
    """Serialize steps to compact deterministic JSON string."""
    if result.deletion_status == DeletionStatus.NOT_APPLICABLE or len(result.steps) == 0:
        return "[]"
    payload = [
        {
            "step_no": s.step_no,
            "phase": s.phase.value,
            "system_id": s.system_id,
            "resource_id": s.resource_id,
            "operation": s.operation.value,
            "state": s.state.value,
            "evidence_id": s.evidence_id,
        }
        for s in result.steps
    ]
    return orjson.dumps(payload).decode("utf-8")


def write_output_csv(results: Sequence[CaseResult], output_path: Path) -> None:
    """Write CaseResult sequence sorted by case_id to output_path."""
    sorted_results = sorted(results, key=lambda r: r.case_id)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(["case_id", "deletion_status", "steps_json"])
        for res in sorted_results:
            writer.writerow(
                [
                    res.case_id,
                    res.deletion_status.value,
                    serialize_steps_json(res),
                ]
            )
