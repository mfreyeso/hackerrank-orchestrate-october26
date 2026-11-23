# Ghost Data Still Exists — `deletion-audit-agent`

<p align="center">
  <img src="./docs/images/ghost_mascot.png" width="280" alt="Ghost Data Still Exists Mascot" />
</p>

Production-grade AI-powered deletion-audit agent for **Northstar Shop** (HackerRank Orchestrate — October 2026).

---

## Problem Statement

Northstar Shop suffered a **$2.4 million loss** after a supposedly deleted customer resurfaced as a "ghost" in its systems. Although internal dashboards marked the deletion workflow as **"Complete,"** weeks later the customer attempted to create a new account and was rejected with: *"This email is already registered."*

Investigation revealed personal data lingering across secondary databases, read/failover replicas, support attachments, search indexes, analytics exports, logs, archives, and backups. Worse, background synchronization and restore jobs actively recreated information that primary account services had purged.

### The Objective

Build an autonomous deletion-audit agent that independently investigates deletion requests, resolves historical and current identities, inspects multi-modal evidence across heterogeneous systems, overrides untrusted workflow claims, and establishes the true ground-truth state as of `audit_at`.

For each request in `dataset/deletion_requests.csv` (518 evaluation cases), the system determines:
1. **Request Intent & Authorization**:
   - `COMPLETE` or `INCOMPLETE` for valid deletion requests.
   - `NOT_APPLICABLE` (short-circuiting with empty `steps_json=[]`) when the user did not authorize deletion (e.g., access requests, data export requests, marketing opt-outs).
2. **Identification of Residual Data & Active Risks**:
   - Prohibited personal records or direct identifiers still exposed (`REPORT_REMAINING_RECORD`, `REPORT_EXPOSED_PII`).
   - Active data synchronization jobs or restore paths capable of resurrecting deleted data (`REPORT_ACTIVE_DATA_FLOW`, `REPORT_RESTORE_RISK`).
3. **Remediation & Evidence-Backed Verification**:
   - For **`INCOMPLETE`** cases: Ordered remediation plan (`DISABLE_DATA_FLOW`, `BLOCK_RESTORE`, `DELETE_RECORD`, `REDACT_RECORD`, `ANONYMIZE_RECORD`) followed by mandatory verification checks (with empty `evidence_id: ""`).
   - For **`COMPLETE`** cases: Verification steps (`VERIFY_RECORD_ABSENT`, `VERIFY_RECORD_PRESENT`, `VERIFY_RECORD_REDACTED`, `VERIFY_RECORD_ANONYMIZED`, etc.) citing participant-visible evidence (`file_id`, `activity_id`, `audit_id`) captured at or before `audit_at`.
   - **Policy Compliance**: Preservation of mandatory audit trails (`SECURITY_AUDIT_LOG`) and compliant account tombstones (`ACCOUNT_TOMBSTONE` retaining internal `user_id` reference while direct PII like name, email, phone, and hash are redacted).

---

## Solution Approach & Architectural Assumptions

Based on analysis of the 32 public ground-truth cases in `sample_output.csv`, `deletion_rules.csv`, `system_activity.csv`, and all artifacts in `dataset/evidence/`, the solution is built around key architectural principles and design assumptions documented in [`docs/assumptions.md`](./docs/assumptions.md):

1. **Lineage-Based Classification for Non-Deletion (`NOT_APPLICABLE`)**:
   - Rather than relying solely on brittle text heuristics on multi-lingual requests, `NOT_APPLICABLE` cases are identified deterministically from `CLASSIFY_REQUEST` intake lineage events in `system_activity.csv` (`source_system="privacy_intake"`, `target_system="privacy_case_management"`, `"non-deletion"` details) occurring within `[requested_at, reported_at + 15m]`.
   - Fallback LLM intent classification (`FakeLLM.classify_intent`) is retained for synthetic API or ad-hoc requests lacking system activity events.

2. **Strict Temporal Window Pruning (`reported_at <= captured_at <= audit_at`)**:
   - Evidence files captured prior to `reported_at` reflect stale pre-workflow states, while files captured strictly after `audit_at` violate the point-in-time audit contract.
   - Pruning evidence strictly to `reported_at <= captured_at <= audit_at` and evaluating newest-first (`captured_at DESC`) narrows the candidate evidence set from 94 files down to an average of **7.31 files per case** across all 550 cases without missing required citations.

3. **Untrusted Workflow Claims & Sequential-Smart Evidence Extraction**:
   - `reported_status` (`COMPLETE`, `PARTIALLY_COMPLETE`, `NOT_STARTED`) is treated as an unverified claim, used solely as a graph routing hint.
   - Sequential extraction scans pruned evidence newest-first, locking each `(system_id, resource_id)` at its most recent grounded observation, while drilling deeper into historical captures inside `[reported_at, audit_at]` only when active risks or SQL replica drift are detected.

4. **Multi-System Evidence Grounding & Replication Drift**:
   - **SQL Snapshots (Sandboxed SQLite)**: Directly detects replication drift where primary tables show a record as `ABSENT` but `*_failover_replica` or `*_read_replica` tables still hold data (`REPORT_REMAINING_RECORD`).
   - **Observability Logs & Streams**: Correlates pipe-delimited operational streams, JSON-lines, and trace IDs to extract read/download/lookup events.
   - **Cohort Lineage Attribution**: Unattributed anonymized analytics profiles (`customer_reference: null`) and unclaimed account deletions are deterministically paired across subject cohorts in `system_activity.csv`.
   - **Document & Multimodal Records**: Extracts grounded facts from PDF exports, structured JSON dumps, and support handover records.

5. **Policy Enforcement & Tombstones**:
   - Preserves `SECURITY_AUDIT_LOG` records as `VERIFY_RECORD_PRESENT`.
   - Audits `ACCOUNT_TOMBSTONE` records on `identity_service`: compliant tombstones emit `VERIFY_RECORD_REDACTED`; tombstones leaking direct PII emit `REPORT_EXPOSED_PII` $\rightarrow$ `REDACT_RECORD` $\rightarrow$ `VERIFY_RECORD_REDACTED`.

6. **Canonical Step Ordering & Strict Serialization**:
   - Every generated `steps_json` strictly adheres to canonical ordering:
     1. **Phase**: `FINDING` $\rightarrow$ `REMEDIATION` $\rightarrow$ `VERIFICATION`
     2. **Operation**: Canonical table precedence (e.g. `REPORT_REMAINING_RECORD` before `REPORT_EXPOSED_PII`; `DISABLE_DATA_FLOW` before `DELETE_RECORD`)
     3. **System ID**: Lexicographical ascending
     4. **Resource ID**: Lexicographical ascending
   - `step_no` is indexed sequentially starting at 1.

---

## Technology Stack & Python Libraries

The solution is built in **Python 3.12+** using modern, production-grade libraries structured across the following architectural layers:

| Layer / Domain | Technologies & Libraries | Role & Purpose |
|---|---|---|
| **Runtime & Packaging** | Python `>=3.12`, `uv`, `hatchling` | Reproducible dependency resolution, lightning-fast virtual environments, and PEP 517/621 builds. |
| **Agent & Workflow Orchestration** | `langgraph` (`>=0.2.35`), `langchain-core` (`>=0.3.10`) | Stateful cyclic graph modeling for decision routing, intent analysis, and investigation stages. |
| **Model Connectivity & LLMs** | `langchain-anthropic` (`>=0.2.3`), `langchain-openai` (`>=0.2.2`), `tiktoken` (`>=0.8.0`) | Provider-agnostic LLM client abstractions, structured schema outputs, and exact token budget tracking. |
| **Data Processing & Analytics** | `polars` (`>=1.9.0`), `sqlglot` (`>=25.24.0`), `sqlite3` (std) | High-throughput columnar parsing of large CSV streams; AST-based SQL analysis and sandboxed SQLite replica drift inspection. |
| **Data Modeling & Validation** | `pydantic` (`>=2.9.0`), `pydantic-settings` (`>=2.5.2`) | Strict type validation for cases, steps, state triples, evidence schemas, and environment configuration. |
| **Document & Vision Extraction** | `pypdf` (`>=5.0.1`), `pdfplumber` (`>=0.11.4`), `pymupdf` (`>=1.24.11`), `pillow` (`>=10.4.0`), `pytesseract` (optional) | Multi-format evidence extraction from PDF support attachments, invoices, and screenshot artifacts. |
| **API & Service Delivery** | `fastapi` (`>=0.115.0`), `uvicorn[standard]` (`>=0.31.0`), `httpx` (`>=0.27.2`) | Asynchronous REST microservice with `/health` and `/audit` endpoints for real-time and batch deletion auditing. |
| **CLI & Operator Tools** | `typer` (`>=0.12.5`) | Ergonomic command-line interface powering `audit run`, `audit eval`, and `audit usage`. |
| **Performance, Cache & Resilience** | `orjson` (`>=3.10.7`), `diskcache` (`>=5.6.3`), `tenacity` (`>=9.0.0`), `cryptography` (`>=43.0.0`) | C-speed JSON serialization for `steps_json`, persistent query caching for zero-token reruns, robust backoff retries, and hash validations. |
| **Observability & Logging** | `structlog` (`>=24.4.0`) | Structured, context-enriched JSON event logging for transparent audit trails. |
| **Testing & Verification** | `pytest` (`>=8.3.3`), `pytest-asyncio` (`>=0.24.0`), `hypothesis` (`>=6.115.0`) | Unit, integration, async, and property-based fuzz tests verifying canonical step ordering and state invariants. |
| **Code Quality & Static Analysis** | `ruff` (`>=0.6.9`), `mypy` (`>=1.11.2`, strict), `pre-commit` (`>=4.0.1`) | Sub-second linting, formatting, and strict type checking with zero missing imports. |

---

## Quick Start & Commands

### 1. Install Dependencies (`uv`)

```bash
uv sync --extra dev
```

### 2. Run Unit, Property-Based, and Integration Tests + Linting + Strict Typecheck

```bash
make test
```

Or run individually:

```bash
uv run pytest
uv run ruff check src/ tests/ evaluation/
uv run mypy src/
```

### 3. Run on Public Sample Split (32 Cases) & Evaluate Against `sample_output.csv`

```bash
make run-sample
make eval
```

This writes `sample_predictions.csv` and generates `evaluation/evaluation_report.md` (mirrored to `code/evaluation/evaluation_report.md`).

### 4. Run on Full Evaluation Dataset (518 Cases) & Generate Usage Report

```bash
make run-full
```

Or via the starter entry point:

```bash
python3 code/main.py
```

This writes and validates `output.csv` (518 rows sorted by `case_id`) at the repository root and writes `evaluation/usage_report.md` (mirrored to `code/evaluation/usage_report.md`).

### 5. Run the FastAPI Service

```bash
uv run uvicorn deletion_audit.api:app --host 0.0.0.0 --port 8000
```

Endpoints:
- `GET /health` — Health check
- `POST /audit` — Audit a single `Case` JSON payload
- `GET /audit/{case_id}` — Audit or fetch cached `CaseResult` by `case_id`

### 6. Package `code.zip` for Submission

```bash
make package
```

Submission URL: https://www.hackerrank.com/contests/hackerrank-orchestrate-october26/challenges/ghost-data-still-exists

---

## Project Layout

```text
.
├── pyproject.toml                  # Dependencies, ruff, mypy (strict), pytest config
├── uv.lock                         # Locked reproducible dependencies
├── Makefile                        # sync, test, run-sample, eval, run-full, usage, package
├── Dockerfile                      # Multi-stage non-root container image
├── .env.example                    # Environment configuration template (no secrets)
├── prompts/                        # Versioned prompt templates with untrusted delimiters
├── src/deletion_audit/
│   ├── config.py                   # AuditSettings (pydantic-settings) + model price table
│   ├── logging.py                  # structlog JSON logger
│   ├── cli.py                      # Typer CLI: `audit run`, `audit eval`, `audit usage`
│   ├── eval_metrics.py             # Precision/recall/F1, field accuracy, LCS sequence metrics
│   ├── api/                        # FastAPI service (/health, POST /audit, GET /audit/{case_id})
│   ├── models/                     # Pydantic v2 domain models & legal (phase, op, state) triples
│   ├── data/                       # Polars CSV loaders & SandboxedSQLSnapshot (read-only sqlite3)
│   ├── evidence/                   # SQL, JSON, TXT, LOG, PDF, PNG, and activity extractors
│   ├── policy/                     # Deterministic identity resolver & PolicyEngine (incl. tombstones)
│   ├── planning/                   # Point-in-time state reconstructor, step planner, canonical sorter
│   ├── llm/                        # Provider-agnostic LLMGateway, FakeLLM, diskcache, UsageTracker
│   └── output/                     #Deterministic output.csv writer & final-file validator
├── code/
│   ├── main.py                     # Starter entry point delegating to deletion_audit.cli
│   └── evaluation/                 # Starter evaluation entry point & mirrored reports
├── evaluation/
│   ├── evaluate.py                 # Standalone evaluation script
│   ├── evaluation_report.md        # Generated evaluation metrics, custom cases, failure analysis
│   ├── usage_report.md             # Generated token usage & cost report for full run
│   └── extra_cases/                # 5 team-authored edge-case scenarios & expected outputs
├── tests/                          # Unit, Hypothesis property-based, security, and API tests
└── docs/
    ├── architecture.md             # Mermaid LangGraph diagram & system design
    └── assumptions.md              # Inferred rules from sample_output.csv & open questions
```

---

## Architecture Overview

See [`docs/architecture.md`](./docs/architecture.md) for the full Mermaid workflow diagram and [`docs/assumptions.md`](./docs/assumptions.md) for observations inferred from `sample_output.csv`.

## Evaluation & Cost Reports

- **Evaluation Report**: [`evaluation/evaluation_report.md`](./evaluation/evaluation_report.md)
- **Token Usage & Cost Report**: [`evaluation/usage_report.md`](./evaluation/usage_report.md)
