# Subagent Execution Plan & Pending Tasks (`docs/subagent_tasks.md`)

This document captures the completed scaffold checklist and defines the **4 parallelizable pending workstreams** designed to be spawned via subagents (`invoke_subagent`). Each subagent has disjoint primary file ownership, explicit inputs/outputs, and verification commands.

> **Mandatory `AGENTS.md` Rule for All Spawned Subagents**:
> Every subagent must append its turn entries to the shared root `log.txt` (`/Users/mario/Documents/Learning_2026/hackerrank_orchestrate/hackerrank-orchestrate-october26/log.txt`) with `parent_agent=Antigravity`, populated `tool=` and `model=` lines, and must only use participant-facing files under `dataset/`.

---

## Part 1: Completed Scaffold Tasks

- [x] **1. Dataset & Evidence Inspection** — Inspected headers/rows of all CSVs in `dataset/`, all 5 evidence modalities (`sql`, `json`, `txt`, `log`, `pdf`, `png`), and verified canonical step ordering across all 32 gold rows in `dataset/sample_output.csv`.
- [x] **2. Dependencies & CI Tooling** — Created `pyproject.toml`, `uv.lock`, `Makefile`, `Dockerfile`, `.env.example`, `.gitignore`, `.pre-commit-config.yaml`, and `.github/workflows/ci.yml`.
- [x] **3. Config, Logging, Typed Models & Loaders** — Built `src/deletion_audit/config.py`, `src/deletion_audit/logging.py`, `src/deletion_audit/models/domain.py`, Polars loaders (`src/deletion_audit/data/loaders.py`), and read-only SQLite sandbox (`src/deletion_audit/data/sql_sandbox.py`).
- [x] **4. Deterministic Identity & Policy Core** — Built `resolve_identity` (`src/deletion_audit/policy/identity.py`) and `PolicyEngine` (`src/deletion_audit/policy/engine.py`) supporting `DELETE`, `REDACT` (including `ACCOUNT_TOMBSTONE`), `ANONYMIZE`, `RETAIN`, `DATA_FLOW`, and `BACKUP_ARCHIVE`.
- [x] **5. State Reconstructor, Planner, Sorter & Validator** — Built `reconstruct_resource_states` (`src/deletion_audit/planning/reconstructor.py`), `canonical_sort_steps` (`src/deletion_audit/planning/ordering.py`), `build_case_plan` (`src/deletion_audit/planning/planner.py`), `validate_case_result` (`src/deletion_audit/planning/validators.py`), and `write_output_csv` / `validate_output_file` (`src/deletion_audit/output/`).
- [x] **6. LLM Gateway, Prompts, Cache & UsageTracker** — Built versioned prompts (`prompts/`), `LLMGateway` + `FakeLLM` (`src/deletion_audit/llm/client.py`), and `UsageTracker` (`src/deletion_audit/llm/usage.py`).
- [x] **7. LangGraph State Machine, CLI & FastAPI** — Built per-case LangGraph with `Send` fan-out (`src/deletion_audit/graph/`), Typer CLI (`src/deletion_audit/cli.py`), `code/main.py`, and FastAPI service (`src/deletion_audit/api/app.py`).
- [x] **8. Evaluation Harness, Extra Cases, Full Run & Docs** — Built `evaluation/evaluate.py`, 5 extra test cases in `evaluation/extra_cases/`, `evaluation/evaluation_report.md`, `evaluation/usage_report.md`, `output.csv` (518 validated rows), `code.zip`, `README.md`, `docs/architecture.md`, and `docs/assumptions.md`.

---

## Part 2: Pending Tasks to Spawn via Subagents

### Subagent 1: `Intent Classification & Non-Deletion Short-Circuit Specialist`

- **Suggested `Role`**: `Intent Classification Engineer`
- **Suggested `TypeName`**: `self`
- **Owned Files**:
  - `src/deletion_audit/llm/client.py` (`_NON_DELETION_PATTERNS`, `_DELETION_KEYWORDS`, `FakeLLM.classify_intent`)
  - `prompts/intent_classification_v1.md`
  - `tests/test_intent_classification.py` (new test file)
- **Task Prompt for Subagent**:
  ```text
  Refine request_text intent classification in `src/deletion_audit/llm/client.py` and `prompts/intent_classification_v1.md` so that:
  1. All 32 sample requests in `dataset/sample_deletion_requests.csv` (including indirect phrasings like case_04 "I'm deleting my account", case_12 "I changed the email on this account before deleting it", case_15 "Close the account completely", and case_26 "confirm that the profile is gone") are accurately classified as `authorizes_deletion=True`.
  2. True non-deletion requests in `dataset/deletion_requests.csv` (e.g., requests that only ask for data export/access copies, email/address updates, marketing opt-outs, or where `system_activity.csv` has `CLASSIFY_REQUEST` as non-deletion) are classified as `authorizes_deletion=False` (`NOT_APPLICABLE`, `steps_json=[]`).
  3. Add unit tests in `tests/test_intent_classification.py` covering all multilingual and indirect deletion phrasings plus non-deletion decoys.
  4. Run `.venv/bin/pytest`, `.venv/bin/ruff check`, and `.venv/bin/mypy src/`, and log your work to `log.txt` per `AGENTS.md` §5.2 with `parent_agent=Antigravity`.
  ```

---

### Subagent 2: `Multimodal PDF & Image Evidence Extractor Specialist`

- **Suggested `Role`**: `Multimodal Evidence Engineer`
- **Suggested `TypeName`**: `self`
- **Owned Files**:
  - `src/deletion_audit/evidence/doc_vision_extractor.py`
  - `prompts/evidence_extraction_v1.md`
  - `tests/test_doc_vision_extractor.py` (new test file)
- **Task Prompt for Subagent**:
  ```text
  Implement complete extraction for all PDF and PNG evidence files under `dataset/evidence/documents/` and `dataset/evidence/images/` in `src/deletion_audit/evidence/doc_vision_extractor.py`:
  1. Inspect all 4 PDFs (`evidence_18`, `evidence_27`, `evidence_55`, `evidence_58`) and all 11 PNG screenshots (`evidence_04`, `evidence_09`, `evidence_14`, `evidence_19`, `evidence_23`, `evidence_28`, `evidence_32`, `evidence_37`, `evidence_42`, `evidence_46`, `evidence_60`) in `dataset/evidence/`.
  2. Extract structured `EvidenceFact` records (`system_id`, `resource_id`, `data_category`, `status`, `matched_identifiers`) for PDFs (using `pypdf`/`pdfplumber` table/text parsing) and PNG console screenshots (using deterministic OCR/metadata/vision-stub backed by `diskcache` and `LLMGateway`).
  3. Ensure untrusted text extracted from PDFs/images passes through `sanitize_untrusted_text`.
  4. Add unit tests in `tests/test_doc_vision_extractor.py` verifying extraction on every PDF and PNG evidence type.
  5. Run `.venv/bin/pytest`, `.venv/bin/ruff check`, and `.venv/bin/mypy src/`, and log your work to `log.txt` per `AGENTS.md` §5.2 with `parent_agent=Antigravity`.
  ```

---

### Subagent 3: `Activity & Anonymized Resource Linkage Specialist`

- **Suggested `Role`**: `Activity Linkage Engineer`
- **Suggested `TypeName`**: `self`
- **Owned Files**:
  - `src/deletion_audit/evidence/activity_extractor.py`
  - `src/deletion_audit/evidence/log_json_extractor.py`
  - `tests/test_activity_linkage.py` (new test file)
- **Task Prompt for Subagent**:
  ```text
  Improve deterministic resource-to-subject linkage in `src/deletion_audit/evidence/activity_extractor.py` and `src/deletion_audit/evidence/log_json_extractor.py`:
  1. Analyze how `system_activity.csv` links anonymized records (`analytics_*` via `ANONYMIZE_RECORD`), redacted support/tombstone records (`support_*`, `tombstone_*` via `REDACT_RECORD`), disabled flows (`data_flow_*` via `DISABLE_DATA_FLOW`), blocked backups (`backup_*` via `BLOCK_RESTORE`), and deleted accounts (`account_*` via `DELETE_RECORD`) to a specific case/user without colliding across cases that share the same `audit_at`.
  2. Ensure cases `case_21` through `case_32` in `dataset/sample_deletion_requests.csv` accurately link their `account_*`, `analytics_*`, `support_*`, `data_flow_*`, `backup_*`, `tombstone_*`, and `audit_record_*` resources in `evidence_92`, `evidence_94`, and `evidence_51`.
  3. Add unit tests in `tests/test_activity_linkage.py`.
  4. Run `.venv/bin/pytest`, `.venv/bin/ruff check`, and `.venv/bin/mypy src/`, and log your work to `log.txt` per `AGENTS.md` §5.2 with `parent_agent=Antigravity`.
  ```

---

### Subagent 4: `State Reconstruction & Multi-Evidence Precedence Specialist`

- **Suggested `Role`**: `State Reconstruction Engineer`
- **Suggested `TypeName`**: `self`
- **Owned Files**:
  - `src/deletion_audit/planning/reconstructor.py`
  - `src/deletion_audit/graph/nodes/__init__.py`
  - `tests/test_reconstruction_and_planning.py`
- **Task Prompt for Subagent**:
  ```text
  Refine point-in-time state reconstruction and multi-evidence precedence in `src/deletion_audit/planning/reconstructor.py` and `src/deletion_audit/graph/nodes/__init__.py`:
  1. Inspect all per-case diffs in `evaluation/evaluation_report.md` against `dataset/sample_output.csv` (specifically `case_03`, `case_05`, `case_09`, `case_17`, `case_18`, `case_20`..`case_32`).
  2. Ensure that when multiple evidence snapshots exist at or before `audit_at`, the reconstructor selects the authoritative point-in-time snapshot (`captured_at <= audit_at`) and does not emit spurious extra resources from earlier superseded snapshots.
  3. Verify that replica drift (`customer_profiles_failover_replica` in `evidence_54` for `case_05`, `customer_data_read_replica` in `evidence_05` for `case_16`) and restore risks (`RESTORE_BACKUP` / `backup_service`) are accurately reconstructed.
  4. Run `make eval` and `make test`, and log your work to `log.txt` per `AGENTS.md` §5.2 with `parent_agent=Antigravity`.
  ```

---

## Part 3: Integration & Verification Gate (After Subagents Complete)

Once the 4 subagents finish and report back:
1. Run `make test` (`pytest`, `ruff`, `mypy --strict src/`) to confirm zero regressions or type/lint errors.
2. Run `make eval` to regenerate `evaluation/evaluation_report.md` (and `code/evaluation/evaluation_report.md`) against `dataset/sample_output.csv`.
3. Run `make run-full` to regenerate `output.csv` (518 rows) and `evaluation/usage_report.md` (and `code/evaluation/usage_report.md`).
4. Run `make package` to rebuild `code.zip`.
