"""Evaluation metrics engine comparing predicted output CSV against gold output CSV with bootstrap CIs."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from pathlib import Path

from deletion_audit.models import CaseResult, Step
from deletion_audit.output.validator import validate_output_file

StepTuple = tuple[str, str, str, str, str, str]


def _to_step_tuple(step: Step) -> StepTuple:
    return (
        step.phase.value,
        step.system_id,
        step.resource_id,
        step.operation.value,
        step.state.value,
        step.evidence_id,
    )


def _lcs_length(seq_a: list[StepTuple], seq_b: list[StepTuple]) -> int:
    """Compute Longest Common Subsequence length for two step sequences."""
    n, m = len(seq_a), len(seq_b)
    if n == 0 or m == 0:
        return 0
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if seq_a[i - 1] == seq_b[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])
    return dp[n][m]


@dataclass(frozen=True)
class BootstrapMetricCI:
    """Bootstrap summary statistics for an evaluation metric."""

    mean: float
    std_err: float
    ci_lower: float
    ci_upper: float


@dataclass(frozen=True)
class _PerCaseEvalRecord:
    """Intermediate per-case metrics used for point estimates and bootstrap resampling."""

    case_id: str
    gold_status: str
    pred_status: str
    gold_step_count: int
    pred_step_count: int
    status_match: int
    tp: int
    pred_set_count: int
    gold_set_count: int
    exact_seq_match: int
    order_sim: float


@dataclass(frozen=True)
class CaseFailureDiff:
    case_id: str
    gold_status: str
    pred_status: str
    missing_steps: tuple[StepTuple, ...]
    extra_steps: tuple[StepTuple, ...]
    order_match: bool


@dataclass(frozen=True)
class EvaluationSummary:
    total_cases: int
    status_correct: int
    status_accuracy: float
    step_precision: float
    step_recall: float
    step_f1: float
    field_accuracies: dict[str, float]
    exact_sequence_matches: int
    exact_sequence_accuracy: float
    order_similarity: float
    failures: tuple[CaseFailureDiff, ...]
    bootstrap_metrics: dict[str, BootstrapMetricCI] | None = None
    per_case_comparisons: tuple[tuple[str, str, str, int, int, bool], ...] = ()


def _compute_aggregate_metrics(records: list[_PerCaseEvalRecord]) -> dict[str, float]:
    """Compute the six scalar evaluation metrics for a sample of per-case records."""
    n = len(records)
    if n == 0:
        return {
            "status_accuracy": 0.0,
            "step_precision": 1.0,
            "step_recall": 1.0,
            "step_f1": 1.0,
            "exact_sequence_accuracy": 0.0,
            "order_similarity": 0.0,
        }

    status_acc = sum(r.status_match for r in records) / n
    tp_total = sum(r.tp for r in records)
    pred_total = sum(r.pred_set_count for r in records)
    gold_total = sum(r.gold_set_count for r in records)

    precision = tp_total / pred_total if pred_total > 0 else 1.0
    recall = tp_total / gold_total if gold_total > 0 else 1.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    exact_seq_acc = sum(r.exact_seq_match for r in records) / n
    order_sim = sum(r.order_sim for r in records) / n

    return {
        "status_accuracy": status_acc,
        "step_precision": precision,
        "step_recall": recall,
        "step_f1": f1,
        "exact_sequence_accuracy": exact_seq_acc,
        "order_similarity": order_sim,
    }


def _bootstrap_confidence_intervals(
    records: list[_PerCaseEvalRecord],
    *,
    n_iterations: int = 1000,
    seed: int = 42,
) -> dict[str, BootstrapMetricCI]:
    """Run deterministic case-level bootstrap resampling across `n_iterations` replicates."""
    if not records:
        return {}

    rng = random.Random(seed)
    n = len(records)
    metric_keys = (
        "status_accuracy",
        "step_precision",
        "step_recall",
        "step_f1",
        "exact_sequence_accuracy",
        "order_similarity",
    )
    replicates: dict[str, list[float]] = {k: [] for k in metric_keys}

    for _ in range(n_iterations):
        sample = [records[rng.randrange(n)] for _ in range(n)]
        agg = _compute_aggregate_metrics(sample)
        for k in metric_keys:
            replicates[k].append(agg[k])

    cis: dict[str, BootstrapMetricCI] = {}
    for k in metric_keys:
        vals = sorted(replicates[k])
        mean = sum(vals) / len(vals)
        variance = sum((v - mean) ** 2 for v in vals) / max(len(vals) - 1, 1)
        std_err = math.sqrt(variance)
        idx_lo = int(0.025 * (len(vals) - 1))
        idx_hi = int(0.975 * (len(vals) - 1))
        cis[k] = BootstrapMetricCI(
            mean=mean,
            std_err=std_err,
            ci_lower=vals[idx_lo],
            ci_upper=vals[idx_hi],
        )
    return cis


def evaluate_predictions(
    pred_csv: Path,
    gold_csv: Path,
    *,
    n_bootstrap: int = 1000,
    bootstrap_seed: int = 42,
) -> EvaluationSummary:
    """Compare predictions against gold CSV and compute point + bootstrap metrics."""
    gold_results = validate_output_file(gold_csv)
    gold_by_id: dict[str, CaseResult] = {r.case_id: r for r in gold_results}
    pred_results = validate_output_file(pred_csv, expected_case_ids=list(gold_by_id.keys()))
    pred_by_id: dict[str, CaseResult] = {r.case_id: r for r in pred_results}

    total_cases = len(gold_by_id)
    status_correct = 0
    exact_seq_matches = 0
    similarity_scores: list[float] = []

    tp_total = 0
    pred_step_total = 0
    gold_step_total = 0

    field_names = ("step_no", "phase", "system_id", "resource_id", "operation", "state", "evidence_id")
    field_hits: dict[str, int] = dict.fromkeys(field_names, 0)
    aligned_pairs_total = 0

    failures: list[CaseFailureDiff] = []
    case_records: list[_PerCaseEvalRecord] = []
    comparisons: list[tuple[str, str, str, int, int, bool]] = []

    for case_id in sorted(gold_by_id):
        gold = gold_by_id[case_id]
        pred = pred_by_id[case_id]

        status_matched = pred.deletion_status == gold.deletion_status
        if status_matched:
            status_correct += 1

        gold_tuples = [_to_step_tuple(s) for s in gold.steps]
        pred_tuples = [_to_step_tuple(s) for s in pred.steps]

        gold_set = set(gold_tuples)
        pred_set = set(pred_tuples)

        tp = len(gold_set & pred_set)
        tp_total += tp
        pred_step_total += len(pred_set)
        gold_step_total += len(gold_set)

        is_exact_seq = status_matched and pred_tuples == gold_tuples
        if is_exact_seq:
            exact_seq_matches += 1

        max_len = max(len(gold_tuples), len(pred_tuples))
        if max_len == 0:
            sim = 1.0 if status_matched else 0.0
        else:
            lcs = _lcs_length(pred_tuples, gold_tuples)
            sim = lcs / max_len
        similarity_scores.append(sim)

        case_records.append(
            _PerCaseEvalRecord(
                case_id=case_id,
                gold_status=gold.deletion_status.value,
                pred_status=pred.deletion_status.value,
                gold_step_count=len(gold.steps),
                pred_step_count=len(pred.steps),
                status_match=1 if status_matched else 0,
                tp=tp,
                pred_set_count=len(pred_set),
                gold_set_count=len(gold_set),
                exact_seq_match=1 if is_exact_seq else 0,
                order_sim=sim,
            )
        )
        comparisons.append(
            (
                case_id,
                gold.deletion_status.value,
                pred.deletion_status.value,
                len(gold.steps),
                len(pred.steps),
                is_exact_seq,
            )
        )

        # Field-level accuracy on aligned positions + (phase, system_id, resource_id) matches
        gold_by_res = {(s.phase, s.system_id, s.resource_id): s for s in gold.steps}
        for p_step in pred.steps:
            g_step = gold_by_res.get((p_step.phase, p_step.system_id, p_step.resource_id))
            if g_step is None and p_step.step_no <= len(gold.steps):
                g_step = gold.steps[p_step.step_no - 1]
            if g_step is not None:
                aligned_pairs_total += 1
                if p_step.step_no == g_step.step_no:
                    field_hits["step_no"] += 1
                if p_step.phase == g_step.phase:
                    field_hits["phase"] += 1
                if p_step.system_id == g_step.system_id:
                    field_hits["system_id"] += 1
                if p_step.resource_id == g_step.resource_id:
                    field_hits["resource_id"] += 1
                if p_step.operation == g_step.operation:
                    field_hits["operation"] += 1
                if p_step.state == g_step.state:
                    field_hits["state"] += 1
                if p_step.evidence_id == g_step.evidence_id:
                    field_hits["evidence_id"] += 1

        if not is_exact_seq:
            missing = tuple(t for t in gold_tuples if t not in pred_set)
            extra = tuple(t for t in pred_tuples if t not in gold_set)
            failures.append(
                CaseFailureDiff(
                    case_id=case_id,
                    gold_status=gold.deletion_status.value,
                    pred_status=pred.deletion_status.value,
                    missing_steps=missing,
                    extra_steps=extra,
                    order_match=(pred_tuples == gold_tuples),
                )
            )

    precision = tp_total / pred_step_total if pred_step_total > 0 else 1.0
    recall = tp_total / gold_step_total if gold_step_total > 0 else 1.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

    denom_pairs = max(aligned_pairs_total, 1)
    field_accs = {k: v / denom_pairs for k, v in field_hits.items()}
    bootstrap_cis = _bootstrap_confidence_intervals(
        case_records,
        n_iterations=n_bootstrap,
        seed=bootstrap_seed,
    )

    return EvaluationSummary(
        total_cases=total_cases,
        status_correct=status_correct,
        status_accuracy=status_correct / max(total_cases, 1),
        step_precision=precision,
        step_recall=recall,
        step_f1=f1,
        field_accuracies=field_accs,
        exact_sequence_matches=exact_seq_matches,
        exact_sequence_accuracy=exact_seq_matches / max(total_cases, 1),
        order_similarity=sum(similarity_scores) / max(len(similarity_scores), 1),
        failures=tuple(failures),
        bootstrap_metrics=bootstrap_cis,
        per_case_comparisons=tuple(comparisons),
    )


def render_evaluation_report(summary: EvaluationSummary) -> str:
    """Render evaluation/evaluation_report.md with metrics, bootstrap CIs, custom test cases, and failure analysis."""
    lines = [
        "# Deletion Audit Agent — Evaluation Report (`evaluation_report.md`)",
        "",
        f"## 1. Quantitative Evaluation Metrics (Public Sample Split: {summary.total_cases} Cases)",
        "",
        "| Metric | Score | Details |",
        "| --- | ---: | --- |",
        f"| **Case-Level Deletion-Status Accuracy** | **{summary.status_accuracy * 100:.2f}%** | {summary.status_correct} / {summary.total_cases} cases matched (`COMPLETE` / `INCOMPLETE` / `NOT_APPLICABLE`) |",
        f"| **Step-Level Precision** | **{summary.step_precision * 100:.2f}%** | Exact match on `(phase, system_id, resource_id, operation, state, evidence_id)` tuples |",
        f"| **Step-Level Recall** | **{summary.step_recall * 100:.2f}%** | Recall across all gold steps in `sample_output.csv` |",
        f"| **Step-Level F1 Score** | **{summary.step_f1 * 100:.2f}%** | Harmonic mean of step-level precision and recall |",
        f"| **Exact Sequence Accuracy** | **{summary.exact_sequence_accuracy * 100:.2f}%** | {summary.exact_sequence_matches} / {summary.total_cases} cases with 100% identical ordered `steps_json` |",
        f"| **Order-Sensitive Sequence Similarity (LCS)** | **{summary.order_similarity * 100:.2f}%** | Normalized Longest Common Subsequence similarity across step arrays |",
        "",
    ]

    if summary.bootstrap_metrics:
        point_map = {
            "status_accuracy": ("Case-Level Deletion-Status Accuracy", summary.status_accuracy),
            "step_precision": ("Step-Level Precision", summary.step_precision),
            "step_recall": ("Step-Level Recall", summary.step_recall),
            "step_f1": ("Step-Level F1 Score", summary.step_f1),
            "exact_sequence_accuracy": ("Exact Sequence Accuracy", summary.exact_sequence_accuracy),
            "order_similarity": ("Order-Sensitive Sequence Similarity (LCS)", summary.order_similarity),
        }
        lines.extend(
            [
                f"### 1.1 Bootstrap Confidence Intervals (1,000 Resamples on Public Sample Split: {summary.total_cases} Cases)",
                "",
                "| Metric | Point Estimate | Bootstrap Mean | Std. Error | 95% CI [Lower, Upper] |",
                "| --- | ---: | ---: | ---: | ---: |",
            ]
        )
        for key, (label, point_val) in point_map.items():
            ci = summary.bootstrap_metrics.get(key)
            if ci is not None:
                lines.append(
                    f"| **{label}** | {point_val * 100:.2f}% | {ci.mean * 100:.2f}% | "
                    f"{ci.std_err * 100:.2f}% | [{ci.ci_lower * 100:.2f}%, {ci.ci_upper * 100:.2f}%] |"
                )
        lines.append("")

    lines.extend(
        [
            "### Per-Field Accuracy (Aligned Steps)",
            "",
            "| Field | Accuracy |",
            "| --- | ---: |",
        ]
    )
    for field_name, acc in summary.field_accuracies.items():
        lines.append(f"| `{field_name}` | {acc * 100:.2f}% |")

    if summary.per_case_comparisons:
        lines.extend(
            [
                "",
                "### Per-Case Predicted vs. Expected (`dataset/sample_output.csv`) Comparison",
                "",
                "| `case_id` | Expected Status | Predicted Status | Expected Steps | Predicted Steps | Exact Match |",
                "| --- | --- | --- | ---: | ---: | :---: |",
            ]
        )
        for cid, g_stat, p_stat, g_cnt, p_cnt, is_ex in summary.per_case_comparisons:
            mark = "PASS" if is_ex else "DIFF"
            lines.append(f"| `{cid}` | `{g_stat}` | `{p_stat}` | {g_cnt} | {p_cnt} | {mark} |")

    lines.extend(
        [
            "",
            "---",
            "",
            "## 2. Team-Authored Additional Evaluation Cases (`evaluation/extra_cases/`)",
            "",
            "We authored five additional adversarial and edge-case scenarios in `evaluation/extra_cases/extra_requests.csv` and `evaluation/extra_cases/extra_expected_output.csv`:",
            "",
            "### Case 1: `extra_case_01` — Non-Deletion Request (`NOT_APPLICABLE` Short-Circuit)",
            "- **Scenario**: Customer submits a privacy ticket asking only to download an archive copy of their order history while explicitly keeping their account active.",
            "- **Input `request_text`**: `\"Hi, I only want a copy of my personal data and order history for my tax records. Please do not delete my account.\"`",
            "- **Expected Verdict**: `deletion_status = NOT_APPLICABLE`, `steps_json = []`.",
            "",
            "### Case 2: `extra_case_02` — Account Tombstone Leaking Historical `email_hash`",
            "- **Scenario**: Primary `account_service` record (`account_9001`) is deleted and `security_service` audit log (`audit_record_9001`) is properly retained, but `identity_service` tombstone (`tombstone_9001`) still exposes a non-null `email_hash` alongside the permitted `user_id`.",
            "- **Expected Verdict**: `deletion_status = INCOMPLETE`.",
            "- **Expected Steps**:",
            "  1. `FINDING`: `identity_service` / `tombstone_9001` / `REPORT_EXPOSED_PII` / `PRESENT` (`evidence_extra_02`)",
            "  2. `REMEDIATION`: `identity_service` / `tombstone_9001` / `REDACT_RECORD` / `REDACTED` (`\"\"`)",
            "  3. `VERIFICATION`: `account_service` / `account_9001` / `VERIFY_RECORD_ABSENT` / `ABSENT` (`\"\"`)",
            "  4. `VERIFICATION`: `security_service` / `audit_record_9001` / `VERIFY_RECORD_PRESENT` / `PRESENT` (`\"\"`)",
            "  5. `VERIFICATION`: `identity_service` / `tombstone_9001` / `VERIFY_RECORD_REDACTED` / `REDACTED` (`\"\"`)",
            "",
            "### Case 3: `extra_case_03` — Active Synchronization Job Recreating Search Index Entry",
            "- **Scenario**: Primary profile (`account_9002`) was deleted, but an active continuous sync connector (`data_flow_9002` on `integration_service`) repopulated `search_9002` on `search_service`.",
            "- **Expected Verdict**: `deletion_status = INCOMPLETE`.",
            "- **Expected Steps**:",
            "  1. `FINDING`: `search_service` / `search_9002` / `REPORT_REMAINING_RECORD` / `PRESENT` (`evidence_extra_03`)",
            "  2. `FINDING`: `integration_service` / `data_flow_9002` / `REPORT_ACTIVE_DATA_FLOW` / `ACTIVE` (`evidence_extra_03`)",
            "  3. `REMEDIATION`: `integration_service` / `data_flow_9002` / `DISABLE_DATA_FLOW` / `DISABLED` (`\"\"`)",
            "  4. `REMEDIATION`: `search_service` / `search_9002` / `DELETE_RECORD` / `ABSENT` (`\"\"`)",
            "  5. `VERIFICATION`: `account_service` / `account_9002` / `VERIFY_RECORD_ABSENT` / `ABSENT` (`\"\"`)",
            "  6. `VERIFICATION`: `search_service` / `search_9002` / `VERIFY_RECORD_ABSENT` / `ABSENT` (`\"\"`)",
            "  7. `VERIFICATION`: `integration_service` / `data_flow_9002` / `VERIFY_DATA_FLOW_DISABLED` / `DISABLED` (`\"\"`)",
            "",
            "### Case 4: `extra_case_04` — Unblocked Backup Archive Restore Risk",
            "- **Scenario**: Primary profile (`account_9003`) is absent and security audit log (`audit_record_9003`) is retained, but `backup_service` archive (`backup_9003`) still has `restore_allowed = true`.",
            "- **Expected Verdict**: `deletion_status = INCOMPLETE`.",
            "- **Expected Steps**:",
            "  1. `FINDING`: `backup_service` / `backup_9003` / `REPORT_RESTORE_RISK` / `ACTIVE` (`evidence_extra_04`)",
            "  2. `REMEDIATION`: `backup_service` / `backup_9003` / `BLOCK_RESTORE` / `BLOCKED` (`\"\"`)",
            "  3. `VERIFICATION`: `account_service` / `account_9003` / `VERIFY_RECORD_ABSENT` / `ABSENT` (`\"\"`)",
            "  4. `VERIFICATION`: `security_service` / `audit_record_9003` / `VERIFY_RECORD_PRESENT` / `PRESENT` (`\"\"`)",
            "  5. `VERIFICATION`: `backup_service` / `backup_9003` / `VERIFY_RESTORE_BLOCKED` / `BLOCKED` (`\"\"`)",
            "",
            "### Case 5: `extra_case_05` — Historical Email Change Leaking in Shared Support Conversation",
            "- **Scenario**: Customer changed their email from `old.alias@yahoo.com` to `new.alias@proton.me` in `user_audit_log.csv` prior to `audit_at`. The account (`account_9004`) was deleted under the new email, but a shared support thread (`support_9004` on `support_platform`) still exposes `old.alias@yahoo.com`.",
            "- **Expected Verdict**: `deletion_status = INCOMPLETE`.",
            "- **Expected Steps**:",
            "  1. `FINDING`: `support_platform` / `support_9004` / `REPORT_EXPOSED_PII` / `PRESENT` (`evidence_extra_05`)",
            "  2. `REMEDIATION`: `support_platform` / `support_9004` / `REDACT_RECORD` / `REDACTED` (`\"\"`)",
            "  3. `VERIFICATION`: `account_service` / `account_9004` / `VERIFY_RECORD_ABSENT` / `ABSENT` (`\"\"`)",
            "  4. `VERIFICATION`: `support_platform` / `support_9004` / `VERIFY_RECORD_REDACTED` / `REDACTED` (`\"\"`)",
            "",
            "---",
            "",
            "## 3. Failures Found and Improvements Made",
            "",
            "1. **Replication Drift in Multi-Table SQL Snapshots**:",
            "   - *Failure Found*: Early state reconstruction treated primary and failover replica tables in `evidence_54` (`customer_accounts_failover_replica_20260902.sql`) and `evidence_05` (`customer_data_read_replica_20260921.sql`) equally, allowing `ABSENT` in the primary table to mask `PRESENT` in the failover/read replica (`case_05` and `case_16`).",
            "   - *Improvement Made*: Added deterministic status-severity tie-breaking in `reconstruct_resource_states` so that at identical timestamps, replica exposure (`PRESENT_IDENTIFIABLE`) overrides primary absence.",
            "2. **Log Trace Correlation Across Multi-Line Observability Exports**:",
            "   - *Failure Found*: In `evidence_01` (`service_events_ap_south_20260915.log`), subject emails (`lookup_key`, `subject_key`, `subject_ref`) are logged on `*_started` lines while `resource_id` and `http_status`/`rows` appear on subsequent lines sharing only `trace_id`.",
            "   - *Improvement Made*: Updated `extract_log_facts` to index identifiers by `trace_id` and support `record_lookup`, `export_metadata_read_completed`, `analytics_profile_read`, `message_read`, `restore_authorization_completed`, `requestId`/`function`, and pipe-delimited logs.",
            "3. **Strict Timestamp Pruning & Lineage-Guided Routing**:",
            "   - *Failure Found*: Full-manifest fan-out across all historical files (`captured_at <= audit_at`) caused excessive file scanning and relied on `request_text` routing plus hardcoded sample overrides.",
            "   - *Improvement Made*: Pruned `evidence_files.csv` strictly to `reported_at <= captured_at <= audit_at` (`captured_at DESC`), routed sequentially by `reported_status`, and determined `NOT_APPLICABLE` from `CLASSIFY_REQUEST` lineage events.",
            "",
        ]
    )

    if summary.failures:
        lines.extend(
            [
                "## 4. Per-Case Diffs on Sample Set",
                "",
            ]
        )
        for diff in summary.failures:
            lines.append(
                f"- **`{diff.case_id}`**: gold_status=`{diff.gold_status}`, pred_status=`{diff.pred_status}`, "
                f"missing={len(diff.missing_steps)}, extra={len(diff.extra_steps)}, order_match={diff.order_match}"
            )
    else:
        lines.extend(
            [
                "## 4. Per-Case Diffs on Sample Set",
                "",
                f"Zero failures on `sample_output.csv` ({summary.total_cases}/{summary.total_cases} exact match).",
                "",
            ]
        )

    return "\n".join(lines)
