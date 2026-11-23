"""Final output.csv validator enforcing schema, row count, sorting, and canonical step rules."""

from __future__ import annotations

import csv
from collections.abc import Sequence
from pathlib import Path

import orjson
from pydantic import ValidationError

from deletion_audit.models import CaseResult, DeletionStatus, Step
from deletion_audit.planning.validators import validate_case_result


class OutputValidationError(ValueError):
    """Raised when an output CSV violates the project contract."""


def validate_output_file(
    csv_path: Path,
    *,
    expected_case_ids: Sequence[str] | None = None,
) -> list[CaseResult]:
    """Validate an output CSV file and return parsed CaseResult objects.

    Raises OutputValidationError if any contract rule is violated.
    """
    if not csv_path.exists():
        msg = f"Output file does not exist: {csv_path}"
        raise OutputValidationError(msg)

    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        rows = list(reader)

    if not rows:
        raise OutputValidationError("Output CSV is empty")

    header = rows[0]
    if header != ["case_id", "deletion_status", "steps_json"]:
        msg = f"Invalid header {header}; expected ['case_id', 'deletion_status', 'steps_json']"
        raise OutputValidationError(msg)

    data_rows = rows[1:]
    case_ids = [r[0] for r in data_rows if len(r) >= 1]

    if case_ids != sorted(case_ids):
        raise OutputValidationError("Rows in output CSV are not sorted by case_id ascending")

    if len(set(case_ids)) != len(case_ids):
        raise OutputValidationError("Duplicate case_id rows found in output CSV")

    if expected_case_ids is not None:
        expected_sorted = sorted(expected_case_ids)
        if case_ids != expected_sorted:
            msg = (
                f"Case ID set mismatch: got {len(case_ids)} rows, "
                f"expected {len(expected_sorted)} rows"
            )
            raise OutputValidationError(msg)

    parsed_results: list[CaseResult] = []
    errors: list[str] = []

    for idx, row in enumerate(data_rows, start=2):
        if len(row) != 3:
            errors.append(f"Line {idx}: expected 3 columns, got {len(row)}")
            continue
        case_id, status_str, steps_raw = row
        try:
            status = DeletionStatus(status_str)
        except ValueError:
            errors.append(f"Line {idx} ({case_id}): invalid deletion_status '{status_str}'")
            continue

        if status == DeletionStatus.NOT_APPLICABLE and steps_raw.strip() != "[]":
            errors.append(
                f"Line {idx} ({case_id}): NOT_APPLICABLE row must have steps_json='[]', got {steps_raw!r}"
            )
            continue

        try:
            raw_list = orjson.loads(steps_raw)
        except orjson.JSONDecodeError as exc:
            errors.append(f"Line {idx} ({case_id}): steps_json is not valid JSON: {exc}")
            continue

        if not isinstance(raw_list, list):
            errors.append(f"Line {idx} ({case_id}): steps_json must be a JSON array")
            continue

        try:
            steps = tuple(Step.model_validate(item) for item in raw_list)
            result = CaseResult(case_id=case_id, deletion_status=status, steps=steps)
        except ValidationError as exc:
            errors.append(f"Line {idx} ({case_id}): schema validation failed: {exc}")
            continue

        case_errors = validate_case_result(result)
        errors.extend(case_errors)
        parsed_results.append(result)

    if errors:
        joined = "\n".join(errors[:25])
        raise OutputValidationError(f"Output CSV validation failed ({len(errors)} errors):\n{joined}")

    return parsed_results
