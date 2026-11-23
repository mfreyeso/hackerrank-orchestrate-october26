"""Typer CLI entry point: `audit run`, `audit eval`, and `audit usage`."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated, Literal

import typer

from deletion_audit.config import AuditSettings
from deletion_audit.data import load_dataset_bundle
from deletion_audit.eval_metrics import evaluate_predictions, render_evaluation_report
from deletion_audit.graph import run_cases_concurrently
from deletion_audit.llm import LLMGateway, UsageTracker
from deletion_audit.logging import configure_logging, get_logger
from deletion_audit.output import validate_output_file, write_output_csv

app = typer.Typer(
    name="audit",
    help="Northstar Shop Deletion-Audit Agent CLI (Ghost Data Still Exists)",
    no_args_is_help=True,
)
logger = get_logger(__name__)


@app.command("run")
def run_command(
    split: Annotated[
        str,
        typer.Option("--split", help="Dataset split to run: 'sample' (32) or 'full' (518)"),
    ] = "sample",
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Output CSV path"),
    ] = None,
) -> None:
    """Run the deletion-audit graph across the sample or full dataset and validate output."""
    if split not in {"sample", "full"}:
        raise typer.BadParameter("split must be 'sample' or 'full'")
    typed_split: Literal["sample", "full"] = "sample" if split == "sample" else "full"

    settings = AuditSettings()
    configure_logging(settings.log_level)

    out_path = output or (
        Path("sample_predictions.csv") if typed_split == "sample" else Path("output.csv")
    )
    bundle = load_dataset_bundle(settings, split=typed_split)
    usage_tracker = UsageTracker(settings)
    llm = LLMGateway(settings, usage_tracker=usage_tracker)

    try:
        results = asyncio.run(
            run_cases_concurrently(bundle.cases, settings, bundle, llm)
        )
        write_output_csv(results, out_path)
        expected_ids = [c.case_id for c in bundle.cases]
        validate_output_file(out_path, expected_case_ids=expected_ids)

        usage_file = settings.resolved_cache_dir / f"usage_{typed_split}.json"
        usage_tracker.save(usage_file)
        if typed_split == "full" or not (settings.resolved_cache_dir / "usage_latest.json").exists():
            usage_tracker.save(settings.resolved_cache_dir / "usage_latest.json")

        logger.info(
            "audit_run_completed",
            split=typed_split,
            cases=len(results),
            output=str(out_path),
        )
        typer.echo(f"Wrote and validated {len(results)} rows -> {out_path}")
    finally:
        llm.close()


@app.command("eval")
def eval_command(
    predictions: Annotated[
        Path,
        typer.Option("--predictions", "-p", help="Predictions CSV path"),
    ] = Path("sample_predictions.csv"),
    gold: Annotated[
        Path,
        typer.Option("--gold", "-g", help="Gold sample_output.csv path"),
    ] = Path("dataset/sample_output.csv"),
    report: Annotated[
        Path,
        typer.Option("--report", "-r", help="Evaluation Markdown report path"),
    ] = Path("evaluation/evaluation_report.md"),
) -> None:
    """Evaluate predictions against sample_output.csv and write evaluation_report.md."""
    summary = evaluate_predictions(predictions, gold)
    md = render_evaluation_report(summary)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(md, encoding="utf-8")

    code_eval_report = Path("code/evaluation/evaluation_report.md")
    code_eval_report.parent.mkdir(parents=True, exist_ok=True)
    code_eval_report.write_text(md, encoding="utf-8")

    typer.echo(md)


@app.command("usage")
def usage_command(
    report: Annotated[
        Path,
        typer.Option("--report", "-r", help="Usage Markdown report path"),
    ] = Path("evaluation/usage_report.md"),
    total_requests: Annotated[
        int,
        typer.Option("--total-requests", help="Total request count for per-request averages"),
    ] = 518,
) -> None:
    """Write evaluation/usage_report.md from recorded LLM/vision usage telemetry."""
    settings = AuditSettings()
    usage_path = settings.resolved_cache_dir / "usage_full.json"
    if not usage_path.exists():
        usage_path = settings.resolved_cache_dir / "usage_latest.json"

    tracker = UsageTracker.load(settings, usage_path)
    md = tracker.render_markdown_report(total_requests=total_requests)

    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(md, encoding="utf-8")

    code_usage_report = Path("code/evaluation/usage_report.md")
    code_usage_report.parent.mkdir(parents=True, exist_ok=True)
    code_usage_report.write_text(md, encoding="utf-8")

    typer.echo(md)


if __name__ == "__main__":
    app()
