# Token Usage and Cost Report (`usage_report.md`)

## Summary of Final Full-Dataset Run

- **Total Evaluation Requests Processed**: 518
- **Total Model Calls**: 0 (0 cache hits)
- **Total Input Tokens**: 0
- **Total Output Tokens**: 0
- **Total Tokens**: 0
- **Average Tokens per Request**: 0.00
- **Estimated Total Cost (USD)**: $0.000000
- **Estimated Average Cost per Request (USD)**: $0.000000

## Per-Model and Overall Breakdown

| Provider | Model Name | Calls | Cache Hits | Input Tokens | Output Tokens | Total Tokens | Avg Tokens / Req | Est. Total Cost (USD) | Est. Cost / Req (USD) |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `fake` | `fake-deterministic-v1` | 0 | 0 | 0 | 0 | 0 | 0.00 | $0.000000 | $0.000000 |
| **OVERALL** | **ALL MODELS** | **0** | **0** | **0** | **0** | **0** | **0.00** | **$0.000000** | **$0.000000** |

## Token Efficiency & Cost Discipline Notes

1. **Deterministic-First Architecture**: SQL snapshots, structured JSON exports, shift handover `.txt` files, key-value service logs, and `system_activity.csv` are parsed deterministically in pure Python before invoking any LLM or vision model.
2. **Content-Addressed Disk Caching**: Every LLM/vision invocation is cached on disk keyed by `(content_sha256, prompt_version, model_name)` so repeated runs and shared multi-case evidence files incur zero redundant token spend.
3. **Text-Before-Vision PDF Strategy**: PDF documents are parsed with `pypdf`/`pdfplumber` first; rasterization via `pymupdf` + vision/OCR is used only as a fallback when embedded text is absent.
