# Deletion Audit Agent — Evaluation Report (`evaluation_report.md`)

## 1. Quantitative Evaluation Metrics (Public Sample Split: 32 Cases)

| Metric | Score | Details |
| --- | ---: | --- |
| **Case-Level Deletion-Status Accuracy** | **100.00%** | 32 / 32 cases matched (`COMPLETE` / `INCOMPLETE` / `NOT_APPLICABLE`) |
| **Step-Level Precision** | **99.48%** | Exact match on `(phase, system_id, resource_id, operation, state, evidence_id)` tuples |
| **Step-Level Recall** | **98.45%** | Recall across all gold steps in `sample_output.csv` |
| **Step-Level F1 Score** | **98.96%** | Harmonic mean of step-level precision and recall |
| **Exact Sequence Accuracy** | **90.62%** | 29 / 32 cases with 100% identical ordered `steps_json` |
| **Order-Sensitive Sequence Similarity (LCS)** | **98.76%** | Normalized Longest Common Subsequence similarity across step arrays |

### 1.1 Bootstrap Confidence Intervals (1,000 Resamples on Public Sample Split: 32 Cases)

| Metric | Point Estimate | Bootstrap Mean | Std. Error | 95% CI [Lower, Upper] |
| --- | ---: | ---: | ---: | ---: |
| **Case-Level Deletion-Status Accuracy** | 100.00% | 100.00% | 0.00% | [100.00%, 100.00%] |
| **Step-Level Precision** | 99.48% | 99.49% | 0.53% | [98.18%, 100.00%] |
| **Step-Level Recall** | 98.45% | 98.47% | 0.82% | [96.74%, 100.00%] |
| **Step-Level F1 Score** | 98.96% | 98.97% | 0.61% | [97.58%, 100.00%] |
| **Exact Sequence Accuracy** | 90.62% | 90.77% | 5.10% | [81.25%, 100.00%] |
| **Order-Sensitive Sequence Similarity (LCS)** | 98.76% | 98.78% | 0.73% | [97.12%, 100.00%] |

### Per-Field Accuracy (Aligned Steps)

| Field | Accuracy |
| --- | ---: |
| `step_no` | 97.91% |
| `phase` | 100.00% |
| `system_id` | 100.00% |
| `resource_id` | 99.48% |
| `operation` | 100.00% |
| `state` | 100.00% |
| `evidence_id` | 100.00% |

### Per-Case Predicted vs. Expected (`dataset/sample_output.csv`) Comparison

| `case_id` | Expected Status | Predicted Status | Expected Steps | Predicted Steps | Exact Match |
| --- | --- | --- | ---: | ---: | :---: |
| `case_01` | `COMPLETE` | `COMPLETE` | 1 | 1 | PASS |
| `case_02` | `COMPLETE` | `COMPLETE` | 1 | 1 | PASS |
| `case_03` | `COMPLETE` | `COMPLETE` | 3 | 3 | PASS |
| `case_04` | `COMPLETE` | `COMPLETE` | 2 | 2 | PASS |
| `case_05` | `INCOMPLETE` | `INCOMPLETE` | 3 | 3 | PASS |
| `case_06` | `INCOMPLETE` | `INCOMPLETE` | 4 | 4 | PASS |
| `case_07` | `INCOMPLETE` | `INCOMPLETE` | 4 | 4 | PASS |
| `case_08` | `INCOMPLETE` | `INCOMPLETE` | 4 | 4 | PASS |
| `case_09` | `INCOMPLETE` | `INCOMPLETE` | 5 | 5 | PASS |
| `case_10` | `INCOMPLETE` | `INCOMPLETE` | 4 | 4 | PASS |
| `case_11` | `INCOMPLETE` | `INCOMPLETE` | 14 | 14 | PASS |
| `case_12` | `INCOMPLETE` | `INCOMPLETE` | 5 | 5 | PASS |
| `case_13` | `INCOMPLETE` | `INCOMPLETE` | 8 | 8 | PASS |
| `case_14` | `INCOMPLETE` | `INCOMPLETE` | 5 | 5 | PASS |
| `case_15` | `INCOMPLETE` | `INCOMPLETE` | 5 | 5 | PASS |
| `case_16` | `INCOMPLETE` | `INCOMPLETE` | 7 | 7 | PASS |
| `case_17` | `INCOMPLETE` | `INCOMPLETE` | 5 | 5 | DIFF |
| `case_18` | `INCOMPLETE` | `INCOMPLETE` | 14 | 13 | DIFF |
| `case_19` | `INCOMPLETE` | `INCOMPLETE` | 8 | 8 | PASS |
| `case_20` | `INCOMPLETE` | `INCOMPLETE` | 8 | 7 | DIFF |
| `case_21` | `COMPLETE` | `COMPLETE` | 3 | 3 | PASS |
| `case_22` | `INCOMPLETE` | `INCOMPLETE` | 8 | 8 | PASS |
| `case_23` | `INCOMPLETE` | `INCOMPLETE` | 8 | 8 | PASS |
| `case_24` | `INCOMPLETE` | `INCOMPLETE` | 7 | 7 | PASS |
| `case_25` | `COMPLETE` | `COMPLETE` | 3 | 3 | PASS |
| `case_26` | `COMPLETE` | `COMPLETE` | 6 | 6 | PASS |
| `case_27` | `COMPLETE` | `COMPLETE` | 6 | 6 | PASS |
| `case_28` | `COMPLETE` | `COMPLETE` | 6 | 6 | PASS |
| `case_29` | `INCOMPLETE` | `INCOMPLETE` | 14 | 14 | PASS |
| `case_30` | `INCOMPLETE` | `INCOMPLETE` | 14 | 14 | PASS |
| `case_31` | `COMPLETE` | `COMPLETE` | 3 | 3 | PASS |
| `case_32` | `INCOMPLETE` | `INCOMPLETE` | 5 | 5 | PASS |

---

## 2. Team-Authored Additional Evaluation Cases (`evaluation/extra_cases/`)

We authored five additional adversarial and edge-case scenarios in `evaluation/extra_cases/extra_requests.csv` and `evaluation/extra_cases/extra_expected_output.csv`:

### Case 1: `extra_case_01` — Non-Deletion Request (`NOT_APPLICABLE` Short-Circuit)
- **Scenario**: Customer submits a privacy ticket asking only to download an archive copy of their order history while explicitly keeping their account active.
- **Input `request_text`**: `"Hi, I only want a copy of my personal data and order history for my tax records. Please do not delete my account."`
- **Expected Verdict**: `deletion_status = NOT_APPLICABLE`, `steps_json = []`.

### Case 2: `extra_case_02` — Account Tombstone Leaking Historical `email_hash`
- **Scenario**: Primary `account_service` record (`account_9001`) is deleted and `security_service` audit log (`audit_record_9001`) is properly retained, but `identity_service` tombstone (`tombstone_9001`) still exposes a non-null `email_hash` alongside the permitted `user_id`.
- **Expected Verdict**: `deletion_status = INCOMPLETE`.
- **Expected Steps**:
  1. `FINDING`: `identity_service` / `tombstone_9001` / `REPORT_EXPOSED_PII` / `PRESENT` (`evidence_extra_02`)
  2. `REMEDIATION`: `identity_service` / `tombstone_9001` / `REDACT_RECORD` / `REDACTED` (`""`)
  3. `VERIFICATION`: `account_service` / `account_9001` / `VERIFY_RECORD_ABSENT` / `ABSENT` (`""`)
  4. `VERIFICATION`: `security_service` / `audit_record_9001` / `VERIFY_RECORD_PRESENT` / `PRESENT` (`""`)
  5. `VERIFICATION`: `identity_service` / `tombstone_9001` / `VERIFY_RECORD_REDACTED` / `REDACTED` (`""`)

### Case 3: `extra_case_03` — Active Synchronization Job Recreating Search Index Entry
- **Scenario**: Primary profile (`account_9002`) was deleted, but an active continuous sync connector (`data_flow_9002` on `integration_service`) repopulated `search_9002` on `search_service`.
- **Expected Verdict**: `deletion_status = INCOMPLETE`.
- **Expected Steps**:
  1. `FINDING`: `search_service` / `search_9002` / `REPORT_REMAINING_RECORD` / `PRESENT` (`evidence_extra_03`)
  2. `FINDING`: `integration_service` / `data_flow_9002` / `REPORT_ACTIVE_DATA_FLOW` / `ACTIVE` (`evidence_extra_03`)
  3. `REMEDIATION`: `integration_service` / `data_flow_9002` / `DISABLE_DATA_FLOW` / `DISABLED` (`""`)
  4. `REMEDIATION`: `search_service` / `search_9002` / `DELETE_RECORD` / `ABSENT` (`""`)
  5. `VERIFICATION`: `account_service` / `account_9002` / `VERIFY_RECORD_ABSENT` / `ABSENT` (`""`)
  6. `VERIFICATION`: `search_service` / `search_9002` / `VERIFY_RECORD_ABSENT` / `ABSENT` (`""`)
  7. `VERIFICATION`: `integration_service` / `data_flow_9002` / `VERIFY_DATA_FLOW_DISABLED` / `DISABLED` (`""`)

### Case 4: `extra_case_04` — Unblocked Backup Archive Restore Risk
- **Scenario**: Primary profile (`account_9003`) is absent and security audit log (`audit_record_9003`) is retained, but `backup_service` archive (`backup_9003`) still has `restore_allowed = true`.
- **Expected Verdict**: `deletion_status = INCOMPLETE`.
- **Expected Steps**:
  1. `FINDING`: `backup_service` / `backup_9003` / `REPORT_RESTORE_RISK` / `ACTIVE` (`evidence_extra_04`)
  2. `REMEDIATION`: `backup_service` / `backup_9003` / `BLOCK_RESTORE` / `BLOCKED` (`""`)
  3. `VERIFICATION`: `account_service` / `account_9003` / `VERIFY_RECORD_ABSENT` / `ABSENT` (`""`)
  4. `VERIFICATION`: `security_service` / `audit_record_9003` / `VERIFY_RECORD_PRESENT` / `PRESENT` (`""`)
  5. `VERIFICATION`: `backup_service` / `backup_9003` / `VERIFY_RESTORE_BLOCKED` / `BLOCKED` (`""`)

### Case 5: `extra_case_05` — Historical Email Change Leaking in Shared Support Conversation
- **Scenario**: Customer changed their email from `old.alias@yahoo.com` to `new.alias@proton.me` in `user_audit_log.csv` prior to `audit_at`. The account (`account_9004`) was deleted under the new email, but a shared support thread (`support_9004` on `support_platform`) still exposes `old.alias@yahoo.com`.
- **Expected Verdict**: `deletion_status = INCOMPLETE`.
- **Expected Steps**:
  1. `FINDING`: `support_platform` / `support_9004` / `REPORT_EXPOSED_PII` / `PRESENT` (`evidence_extra_05`)
  2. `REMEDIATION`: `support_platform` / `support_9004` / `REDACT_RECORD` / `REDACTED` (`""`)
  3. `VERIFICATION`: `account_service` / `account_9004` / `VERIFY_RECORD_ABSENT` / `ABSENT` (`""`)
  4. `VERIFICATION`: `support_platform` / `support_9004` / `VERIFY_RECORD_REDACTED` / `REDACTED` (`""`)

---

## 3. Failures Found and Improvements Made

1. **Replication Drift in Multi-Table SQL Snapshots**:
   - *Failure Found*: Early state reconstruction treated primary and failover replica tables in `evidence_54` (`customer_accounts_failover_replica_20260902.sql`) and `evidence_05` (`customer_data_read_replica_20260921.sql`) equally, allowing `ABSENT` in the primary table to mask `PRESENT` in the failover/read replica (`case_05` and `case_16`).
   - *Improvement Made*: Added deterministic status-severity tie-breaking in `reconstruct_resource_states` so that at identical timestamps, replica exposure (`PRESENT_IDENTIFIABLE`) overrides primary absence.
2. **Log Trace Correlation Across Multi-Line Observability Exports**:
   - *Failure Found*: In `evidence_01` (`service_events_ap_south_20260915.log`), subject emails (`lookup_key`, `subject_key`, `subject_ref`) are logged on `*_started` lines while `resource_id` and `http_status`/`rows` appear on subsequent lines sharing only `trace_id`.
   - *Improvement Made*: Updated `extract_log_facts` to index identifiers by `trace_id` and support `record_lookup`, `export_metadata_read_completed`, `analytics_profile_read`, `message_read`, `restore_authorization_completed`, `requestId`/`function`, and pipe-delimited logs.
3. **Strict Timestamp Pruning & Lineage-Guided Routing**:
   - *Failure Found*: Full-manifest fan-out across all historical files (`captured_at <= audit_at`) caused excessive file scanning and relied on `request_text` routing plus hardcoded sample overrides.
   - *Improvement Made*: Pruned `evidence_files.csv` strictly to `reported_at <= captured_at <= audit_at` (`captured_at DESC`), routed sequentially by `reported_status`, and determined `NOT_APPLICABLE` from `CLASSIFY_REQUEST` lineage events.

## 4. Per-Case Diffs on Sample Set

- **`case_17`**: gold_status=`INCOMPLETE`, pred_status=`INCOMPLETE`, missing=1, extra=1, order_match=False
- **`case_18`**: gold_status=`INCOMPLETE`, pred_status=`INCOMPLETE`, missing=1, extra=0, order_match=False
- **`case_20`**: gold_status=`INCOMPLETE`, pred_status=`INCOMPLETE`, missing=1, extra=0, order_match=False