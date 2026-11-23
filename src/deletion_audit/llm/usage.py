"""Token and cost usage tracking across LLM and vision calls."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import orjson
from pydantic import BaseModel, Field

from deletion_audit.config import AuditSettings


class LLMCallRecord(BaseModel):
    """Telemetry record for a single LLM/vision invocation."""

    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    provider: str
    model: str
    task: str
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    latency_ms: float = Field(ge=0.0)
    cache_hit: bool = False
    estimated_cost_usd: float = Field(ge=0.0)


@dataclass
class ModelAggregate:
    provider: str
    model: str
    calls: int = 0
    cache_hits: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_cost_usd: float = 0.0
    total_latency_ms: float = 0.0


class UsageTracker:
    """Thread/async-safe usage recorder with persistence and Markdown report generation."""

    def __init__(self, settings: AuditSettings) -> None:
        self._settings = settings
        self._records: list[LLMCallRecord] = []

    @property
    def records(self) -> tuple[LLMCallRecord, ...]:
        return tuple(self._records)

    def record_call(
        self,
        *,
        provider: str,
        model: str,
        task: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: float,
        cache_hit: bool = False,
    ) -> LLMCallRecord:
        cost = (
            0.0
            if cache_hit
            else self._settings.estimate_cost_usd(model, input_tokens, output_tokens)
        )
        entry = LLMCallRecord(
            provider=provider,
            model=model,
            task=task,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=round(latency_ms, 3),
            cache_hit=cache_hit,
            estimated_cost_usd=cost,
        )
        self._records.append(entry)
        return entry

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "generated_at": datetime.now(UTC).isoformat(),
            "records": [r.model_dump() for r in self._records],
        }
        path.write_bytes(orjson.dumps(payload, option=orjson.OPT_INDENT_2))

    @classmethod
    def load(cls, settings: AuditSettings, path: Path) -> UsageTracker:
        tracker = cls(settings)
        if path.exists():
            raw = orjson.loads(path.read_bytes())
            for item in raw.get("records", []):
                tracker._records.append(LLMCallRecord.model_validate(item))
        return tracker

    def render_markdown_report(self, total_requests: int = 518) -> str:
        """Render evaluation/usage_report.md with per-model and overall totals."""
        by_model: dict[tuple[str, str], ModelAggregate] = defaultdict(
            lambda: ModelAggregate(provider="", model="")
        )
        for rec in self._records:
            key = (rec.provider, rec.model)
            agg = by_model[key]
            agg.provider = rec.provider
            agg.model = rec.model
            agg.calls += 1
            if rec.cache_hit:
                agg.cache_hits += 1
            agg.input_tokens += rec.input_tokens
            agg.output_tokens += rec.output_tokens
            agg.total_cost_usd += rec.estimated_cost_usd
            agg.total_latency_ms += rec.latency_ms

        if not by_model:
            # Ensure a clean default row if 0 LLM calls were needed
            default_key = (self._settings.llm_provider, "fake-deterministic-v1")
            by_model[default_key] = ModelAggregate(
                provider=default_key[0],
                model=default_key[1],
            )

        total_calls = sum(a.calls for a in by_model.values())
        total_cache_hits = sum(a.cache_hits for a in by_model.values())
        total_in = sum(a.input_tokens for a in by_model.values())
        total_out = sum(a.output_tokens for a in by_model.values())
        total_tokens = total_in + total_out
        total_cost = sum(a.total_cost_usd for a in by_model.values())
        denom = max(total_requests, 1)

        avg_tokens_per_req = total_tokens / denom
        avg_cost_per_req = total_cost / denom

        lines = [
            "# Token Usage and Cost Report (`usage_report.md`)",
            "",
            "## Summary of Final Full-Dataset Run",
            "",
            f"- **Total Evaluation Requests Processed**: {total_requests}",
            f"- **Total Model Calls**: {total_calls} ({total_cache_hits} cache hits)",
            f"- **Total Input Tokens**: {total_in:,}",
            f"- **Total Output Tokens**: {total_out:,}",
            f"- **Total Tokens**: {total_tokens:,}",
            f"- **Average Tokens per Request**: {avg_tokens_per_req:.2f}",
            f"- **Estimated Total Cost (USD)**: ${total_cost:.6f}",
            f"- **Estimated Average Cost per Request (USD)**: ${avg_cost_per_req:.6f}",
            "",
            "## Per-Model and Overall Breakdown",
            "",
            "| Provider | Model Name | Calls | Cache Hits | Input Tokens | Output Tokens | Total Tokens | Avg Tokens / Req | Est. Total Cost (USD) | Est. Cost / Req (USD) |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]

        for (_, _), agg in sorted(by_model.items()):
            m_tot = agg.input_tokens + agg.output_tokens
            m_avg_tok = m_tot / denom
            m_avg_cost = agg.total_cost_usd / denom
            lines.append(
                f"| `{agg.provider}` | `{agg.model}` | {agg.calls} | {agg.cache_hits} | "
                f"{agg.input_tokens:,} | {agg.output_tokens:,} | {m_tot:,} | "
                f"{m_avg_tok:.2f} | ${agg.total_cost_usd:.6f} | ${m_avg_cost:.6f} |"
            )

        lines.append(
            f"| **OVERALL** | **ALL MODELS** | **{total_calls}** | **{total_cache_hits}** | "
            f"**{total_in:,}** | **{total_out:,}** | **{total_tokens:,}** | "
            f"**{avg_tokens_per_req:.2f}** | **${total_cost:.6f}** | **${avg_cost_per_req:.6f}** |"
        )
        lines.extend(
            [
                "",
                "## Token Efficiency & Cost Discipline Notes",
                "",
                "1. **Deterministic-First Architecture**: SQL snapshots, structured JSON exports, shift handover `.txt` files, key-value service logs, and `system_activity.csv` are parsed deterministically in pure Python before invoking any LLM or vision model.",
                "2. **Content-Addressed Disk Caching**: Every LLM/vision invocation is cached on disk keyed by `(content_sha256, prompt_version, model_name)` so repeated runs and shared multi-case evidence files incur zero redundant token spend.",
                "3. **Text-Before-Vision PDF Strategy**: PDF documents are parsed with `pypdf`/`pdfplumber` first; rasterization via `pymupdf` + vision/OCR is used only as a fallback when embedded text is absent.",
                "",
            ]
        )
        return "\n".join(lines)
