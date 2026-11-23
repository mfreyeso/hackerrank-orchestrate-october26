# Architecture — `deletion-audit-agent`

## 1. Approach Overview and Generalization

Scoring in **Ghost Data Still Exists** requires exact-match fields (`deletion_status`, `step_no`, `phase`, `system_id`, `resource_id`, `operation`, `state`, `evidence_id`) and canonical step ordering at each case's `audit_at` cutoff. To achieve high precision across all **32 public sample cases** and **518 full evaluation requests** without brittle LLM routing or case-specific heuristics, the refactored architecture relies on three core principles:

1. **Lineage-Driven Request Classification (Zero Query-Text Routing)**:
   - Early prototypes classified `request_text` in an LLM `intake` node to short-circuit `NOT_APPLICABLE` requests. That assumption fails when legitimate deletion requests are phrased ambiguously across languages and misses structural system proof.
   - Now, every case enters `identity_resolver`. A request is marked `NOT_APPLICABLE` (`classified_non_deletion = True`, `steps_json = []`) deterministically only when `system_activity.csv` records a `CLASSIFY_REQUEST` lineage event (`"non-deletion"` in `details`) linked to the subject's resolved resource within `[requested_at, reported_at + 15m]` (e.g., `case_533`–`case_542`). An offline `FakeLLM` fallback applies only to synthetic API/unit-test cases outside the dataset.

2. **Strict Temporal Window Pruning (`reported_at <= captured_at <= audit_at`)**:
   - Scanning all 94 evidence files across 550 cases is redundant and risks matching stale pre-deletion snapshots or leaking post-`audit_at` events.
   - `timestamp_lineage_pruner` prunes `evidence_files.csv` strictly to `reported_at <= captured_at <= audit_at` and sorts candidates newest-first (`captured_at DESC`). Across all 550 dataset cases (`32` sample + `518` evaluation), this reduces the search space from **94 files to an average of 7.31 files per case** while retaining 100% of admissible ground-truth evidence citations.

3. **`reported_status` as a Sequential-Smart Routing Hint + Batch Lineage Generalization**:
   - Although `reported_status` (`COMPLETE`, `PARTIALLY_COMPLETE`, `NOT_STARTED`) is an untrusted claim that is frequently falsified, it guides which verification branch (`complete_flow_checker`, `partial_flow_checker`, `not_started_flow_checker`) inspects the pruned manifest.
   - Within the chosen branch, `_run_sequential_smart_extraction` scans files from newest `captured_at` to oldest, locking each grounded `(system_id, resource_id)` at its latest state while continuing to older files in `[reported_at, audit_at]` only for unseen resources, active risk states (`FLOW_ACTIVE`, `RESTORE_ACTIVE`, `PRESENT_IDENTIFIABLE`), or SQLite replica drift (`is_replica_only=True`).
   - To generalize anonymized records (`analytics_*` with `null` PII) and primary `account_*` DROP records whose resource IDs never appear explicitly in `details`, `_build_participant_evidence_index` pre-indexes every JSON, TXT handover, SQL, and trace-correlated LOG artifact, and `_build_batch_lineage_indexes` deterministically pairs unattributed `deletion_worker` activities within the shared `reported_at` cohort window. This generalizes uniformly across the 518 evaluation cases with zero hardcoded per-case overrides and zero LLM token spend during structured audits.

---

## 2. How a Case Is Solved: End-to-End Worked Example (`case_11`)

Consider `case_11` from `dataset/sample_deletion_requests.csv`:

- **Input Row**: `email = novak.tomasz@icloud.com`, `requested_at = 2026-09-09T12:00:00Z`, `reported_status = COMPLETE`, `reported_at = 2026-09-12T12:00:00Z`, `audit_at = 2026-10-01T12:00:00Z`.
- **Deceptive Claim**: The workflow reported `COMPLETE`, yet four downstream copies/risks were still exposed on `2026-10-01T12:00:00Z`.

Here is how the refactored state machine resolves `case_11`:

1. **`identity_resolver`**:
   - Resolves `novak.tomasz@icloud.com` in `user_identities.csv` to `user_32` (`Tomasz Novak`, phone `+48 601 623 422`, `email_hash = c5d7aedd...`) and incorporates any `user_audit_log.csv` mutations dated `<= 2026-10-01T12:00:00Z`.
2. **`timestamp_lineage_pruner`**:
   - Prunes `evidence_files.csv` from **94 files down to 17 files** captured in `[2026-09-12T12:00:00Z, 2026-10-01T12:00:00Z]`, ordered newest-first starting with `evidence_03` (`customer_account_handover_20261001.txt`, `captured_at = 2026-10-01T12:00:00Z`).
   - Inspects `system_activity.csv` around `reported_at`: correlates `activity_3801` (`2026-09-12T11:04:43Z`, `DELETE_RECORD` on `account_service` / `account_4248`, `reported_result = SUCCESS`) within `[reported_at - 90m, reported_at + 15m]`, establishing the primary `DROP` link (`account_4248`), alongside downstream workflow activities (`activity_3814`..`activity_3817` on `search_052`, `support_864`, `analytics_2034`, `data_flow_9522`) and `user_32`-indexed `audit_record_9394`. Confirms `classified_non_deletion = False`.
3. **Router -> `complete_flow_checker` (`_run_sequential_smart_extraction`)**:
   - Because `reported_status == COMPLETE`, the router dispatches `case_11` to `complete_flow_checker`.
   - The first file scanned (`evidence_03`, newest at `2026-10-01T12:00:00Z`) contains six grounded handover lines for `user_32` / `novak.tomasz@icloud.com`:
     - `account_service` / `account_4248` (`USER_PROFILE`, `NOT_FOUND` -> `ABSENT`)
     - `security_service` / `audit_record_9394` (`SECURITY_AUDIT_LOG`, `FOUND` -> `PRESENT_RETAINED`)
     - `search_service` / `search_052` (`SEARCH_INDEX_ENTRY`, `FOUND` -> `PRESENT_IDENTIFIABLE`)
     - `analytics_platform` / `analytics_2034` (`ANALYTICS_PROFILE`, `IDENTIFIABLE` -> `PRESENT_IDENTIFIABLE`)
     - `support_platform` / `support_864` (`SUPPORT_MESSAGE`, `IDENTIFIABLE` -> `PRESENT_IDENTIFIABLE`)
     - `integration_service` / `data_flow_9522` (`DATA_FLOW`, `ACTIVE` -> `FLOW_ACTIVE`)
   - All six `(system_id, resource_id)` keys are locked in `grounded_keys`, preventing older captures in `[reported_at, audit_at]` (such as `evidence_02` or `evidence_01`) from overwriting the authoritative `2026-10-01T12:00:00Z` state.
4. **`state_reconstructor` -> `policy_engine` -> `planner` -> `verifier`**:
   - `reconstruct_resource_states` keeps the grounded `evidence_03` state for each resource (in other cases such as `case_05`, if primary tables show `ABSENT` while a replica table in `evidence_54` shows `account_005` `PRESENT_IDENTIFIABLE` with `is_replica_only=True`, severity tie-breaking preserves the replica finding).
   - `PolicyEngine.evaluate` flags `search_052`, `analytics_2034`, `support_864`, and `data_flow_9522` as non-compliant and marks `account_4248` (`ABSENT`) and `audit_record_9394` (`PRESENT_RETAINED`) as compliant.
   - `build_case_plan` overrides the false `COMPLETE` claim with `INCOMPLETE` and emits **14 canonically sorted steps**: Steps `1–4` (`FINDING`, all citing `evidence_03`), Steps `5–8` (`REMEDIATION`, `evidence_id=""` with `DISABLE_DATA_FLOW` before `DELETE_RECORD` / `REDACT_RECORD` / `ANONYMIZE_RECORD`), and Steps `9–14` (`VERIFICATION`, `evidence_id=""` covering all 6 resources including `account_4248` and `audit_record_9394`).
   - `verifier` confirms schema validity, triple legality, canonical sort order, and valid `evidence_id` citations at `<= audit_at`.

---

## 3. Per-Case LangGraph State Machine

```mermaid
flowchart TD
    START(["START (Case)"]) --> identity_resolver["1. identity_resolver"]
    identity_resolver --> timestamp_lineage_pruner["2. timestamp_lineage_pruner"]
    timestamp_lineage_pruner --> route_status{"3. Route by reported_status"}

    route_status -- "COMPLETE" --> complete_flow_checker["3a. complete_flow_checker"]
    route_status -- "PARTIALLY_COMPLETE" --> partial_flow_checker["3b. partial_flow_checker"]
    route_status -- "NOT_STARTED" --> not_started_flow_checker["3c. not_started_flow_checker"]

    complete_flow_checker --> state_reconstructor["4. state_reconstructor"]
    partial_flow_checker --> state_reconstructor
    not_started_flow_checker --> state_reconstructor

    state_reconstructor --> policy_engine["5. policy_engine"]
    policy_engine --> planner["6. planner"]
    planner --> verifier["7. verifier"]

    verifier -- "needs_rerun == true" --> timestamp_lineage_pruner
    verifier -- "valid / bounded exit" --> END_NODE(["END (CaseResult)"])
```

### Graph Node Reference List

1. **`identity_resolver`** ([nodes/__init__.py](file:///Users/mario/Documents/Learning_2026/hackerrank_orchestrate/hackerrank-orchestrate-october26/src/deletion_audit/graph/nodes/__init__.py#L70-L78)):
   - Resolves the subject's `user_id`, current identifiers (`user_identities.csv`), and historical names/emails/phones/SHA-256 `email_hash` values (`user_audit_log.csv` where `event_time <= audit_at`) into `ResolvedIdentity`.
2. **`timestamp_lineage_pruner`** ([nodes/__init__.py](file:///Users/mario/Documents/Learning_2026/hackerrank_orchestrate/hackerrank-orchestrate-october26/src/deletion_audit/graph/nodes/__init__.py#L80-L105)):
   - Calls `analyze_case_activity` to extract `[requested_at, reported_at]` workflow rows, post-report `[reported_at, audit_at]` rows, `known_resource_ids` (via direct match + participant evidence index + batch-level `reported_at` pairing), primary `DROP` linkage (`has_drop_account_activity`), and `classified_non_deletion` (`CLASSIFY_REQUEST`).
   - Strictly prunes `evidence_files.csv` to `reported_at <= captured_at <= audit_at`, ordered `captured_at DESC`.
3. **Sequential-Smart Flow Checkers (`complete_flow_checker`, `partial_flow_checker`, `not_started_flow_checker`)** ([nodes/__init__.py](file:///Users/mario/Documents/Learning_2026/hackerrank_orchestrate/hackerrank-orchestrate-october26/src/deletion_audit/graph/nodes/__init__.py#L107-L216)):
   - `not_started_flow_checker` immediately returns `{"facts": []}` when `classified_non_deletion` is `True`.
   - Otherwise, all three branches invoke `_run_sequential_smart_extraction`, scanning `pruned_manifest` newest-first across SQL, JSON, TXT, LOG, PDF, and PNG extractors and locking each grounded `(system_id, resource_id)` while preserving active risk flags and replica-only detections (`is_replica_only=True`).
4. **`state_reconstructor`** ([nodes/__init__.py](file:///Users/mario/Documents/Learning_2026/hackerrank_orchestrate/hackerrank-orchestrate-october26/src/deletion_audit/graph/nodes/__init__.py#L218-L300)):
   - Short-circuits to `[]` if `classified_non_deletion` is `True`; otherwise anchors subject-linked primary `account_*` absence / `audit_record_*` retention facts when downstream findings exist and runs `reconstruct_resource_states` to resolve the final point-in-time `ResourceState` tuple at `audit_at`.
5. **`policy_engine`** ([nodes/__init__.py](file:///Users/mario/Documents/Learning_2026/hackerrank_orchestrate/hackerrank-orchestrate-october26/src/deletion_audit/graph/nodes/__init__.py#L302-L306)):
   - Applies `PolicyEngine.evaluate_all` against `deletion_rules.csv` (`DELETE`, `REDACT`, `ANONYMIZE`, `RETAIN`, `ACCOUNT_TOMBSTONE`, `DATA_FLOW`, `BACKUP_ARCHIVE`), honoring `shared_context` rules for support attachments vs. support messages.
6. **`planner`** ([nodes/__init__.py](file:///Users/mario/Documents/Learning_2026/hackerrank_orchestrate/hackerrank-orchestrate-october26/src/deletion_audit/graph/nodes/__init__.py#L308-L325)):
   - Emits `NOT_APPLICABLE` (`steps=[]`) when `classified_non_deletion` is `True`; otherwise delegates to `build_case_plan` to generate `COMPLETE` or `INCOMPLETE` outputs sorted canonically by phase, operation priority, `system_id`, and `resource_id`.
7. **`verifier`** ([nodes/__init__.py](file:///Users/mario/Documents/Learning_2026/hackerrank_orchestrate/hackerrank-orchestrate-october26/src/deletion_audit/graph/nodes/__init__.py#L327-L351)):
   - Validates `CaseResult` enums, consecutive `step_no`, canonical order, and admissible `evidence_id` values (`<= audit_at`), allowing up to `max_verifier_retries` bounded reruns.

---

## 4. Human Audit Entrypoints (Where to Start Reviewing Code)

A human reviewer auditing this codebase should begin at **`build_case_graph`** in [builder.py](file:///Users/mario/Documents/Learning_2026/hackerrank_orchestrate/hackerrank-orchestrate-october26/src/deletion_audit/graph/builder.py#L36-L81) (line `36`) to inspect the entire orchestration topology, then trace through the core execution, lineage, and policy modules in this order:

| Audit Order | Concern | Module & Symbol | Exact Location |
| :---: | --- | --- | --- |
| **1 (Start Here)** | Graph wiring & `reported_status` router | `build_case_graph` & `_route_by_reported_status` | [builder.py](file:///Users/mario/Documents/Learning_2026/hackerrank_orchestrate/hackerrank-orchestrate-october26/src/deletion_audit/graph/builder.py#L20-L81) (lines `20–27`, `36–81`) |
| **2** | Graph state schema & `merge_evidence_facts` reducer | `CaseGraphState` | [state.py](file:///Users/mario/Documents/Learning_2026/hackerrank_orchestrate/hackerrank-orchestrate-october26/src/deletion_audit/graph/state.py#L20-L55) (lines `20–55`) |
| **3** | Strict `[reported_at, audit_at]` pruning | `GraphNodes.timestamp_lineage_pruner` | [nodes/__init__.py](file:///Users/mario/Documents/Learning_2026/hackerrank_orchestrate/hackerrank-orchestrate-october26/src/deletion_audit/graph/nodes/__init__.py#L80-L105) (lines `80–105`) |
| **4** | Sequential-smart manifest scan & locking | `GraphNodes._run_sequential_smart_extraction` | [nodes/__init__.py](file:///Users/mario/Documents/Learning_2026/hackerrank_orchestrate/hackerrank-orchestrate-october26/src/deletion_audit/graph/nodes/__init__.py#L107-L199) (lines `107–199`) |
| **5** | Activity lineage, `CLASSIFY_REQUEST`, & batch pairing | `_build_participant_evidence_index`, `_build_batch_lineage_indexes`, `analyze_case_activity` | [activity_extractor.py](file:///Users/mario/Documents/Learning_2026/hackerrank_orchestrate/hackerrank-orchestrate-october26/src/deletion_audit/evidence/activity_extractor.py#L46-L515) (lines `46–246`, `250–359`, `362–515`) |
| **6** | Multi-format LOG, JSON, TXT, & SQL extractors | `_parse_log_line`, `extract_log_facts`, `extract_sql_snapshot_facts` | [log_json_extractor.py](file:///Users/mario/Documents/Learning_2026/hackerrank_orchestrate/hackerrank-orchestrate-october26/src/deletion_audit/evidence/log_json_extractor.py#L336-L623) (lines `336–623`) & [sql_extractor.py](file:///Users/mario/Documents/Learning_2026/hackerrank_orchestrate/hackerrank-orchestrate-october26/src/deletion_audit/evidence/sql_extractor.py#L168-L237) (lines `168–237`) |
| **7** | Point-in-time state & replica-drift resolution | `reconstruct_resource_states` | [reconstructor.py](file:///Users/mario/Documents/Learning_2026/hackerrank_orchestrate/hackerrank-orchestrate-october26/src/deletion_audit/planning/reconstructor.py#L50-L132) (lines `50–132`) |
| **8** | Policy rule mapping & canonical step planning | `PolicyEngine.evaluate` & `build_case_plan` | [engine.py](file:///Users/mario/Documents/Learning_2026/hackerrank_orchestrate/hackerrank-orchestrate-october26/src/deletion_audit/policy/engine.py#L42-L201) (lines `42–201`) & [planner.py](file:///Users/mario/Documents/Learning_2026/hackerrank_orchestrate/hackerrank-orchestrate-october26/src/deletion_audit/planning/planner.py#L15-L108) (lines `15–108`) |

---

## 5. Security, Sandbox & Determinism Controls

- **Untrusted Evidence Delimiting & Prompt-Injection Defense**: Prompts isolate untrusted inputs inside `<untrusted_request_text>` and `<untrusted_evidence>` boundaries; `sanitize_untrusted_text` strips boundary escapes and neutralizes directive overrides.
- **Read-Only In-Memory SQLite Sandbox**: `SandboxedSQLSnapshot` loads `.sql` captures into `:memory:` with a `sqlite3.set_authorizer` callback that blocks `ATTACH`, `DETACH`, `PRAGMA` mutations, `DELETE`, `UPDATE`, and `DROP` during read queries.
- **Filesystem Sandbox**: `AuditSettings.resolve_dataset_file` resolves all manifest paths inside `dataset/` and raises `PermissionError` on any directory traversal attempt (`..`).
- **Deterministic Offline Reproducibility**: All 518 evaluation rows and all 32 sample rows resolve deterministically (`0` live LLM tokens, `$0.00` API cost) via pure-Python extraction, lineage correlation, and policy evaluation.
