"""CLI-invokable evaluation script scoring predictions against sample_output.csv."""

from __future__ import annotations

import argparse
from pathlib import Path

from deletion_audit.eval_metrics import evaluate_predictions, render_evaluation_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Score predictions CSV against gold sample_output.csv")
    parser.add_argument(
        "--predictions",
        type=Path,
        default=Path("sample_predictions.csv"),
        help="Path to predictions CSV",
    )
    parser.add_argument(
        "--gold",
        type=Path,
        default=Path("dataset/sample_output.csv"),
        help="Path to gold sample_output.csv",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("evaluation/evaluation_report.md"),
        help="Path to write Markdown evaluation report",
    )
    args = parser.parse_args()

    summary = evaluate_predictions(args.predictions, args.gold)
    report_md = render_evaluation_report(summary)

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(report_md, encoding="utf-8")

    # Also mirror to code/evaluation/evaluation_report.md for starter layout compatibility
    mirror_path = Path("code/evaluation/evaluation_report.md")
    mirror_path.parent.mkdir(parents=True, exist_ok=True)
    mirror_path.write_text(report_md, encoding="utf-8")

    print(report_md)


if __name__ == "__main__":
    main()
