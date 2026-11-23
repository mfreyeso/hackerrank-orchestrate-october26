"""Starter evaluation entry point `python3 code/evaluation/main.py`."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from deletion_audit.cli import eval_command, run_command  # noqa: E402


def main() -> None:
    sample_pred = ROOT_DIR / "sample_predictions.csv"
    run_command(split="sample", output=sample_pred)
    eval_command(
        predictions=sample_pred,
        gold=ROOT_DIR / "dataset" / "sample_output.csv",
        report=ROOT_DIR / "evaluation" / "evaluation_report.md",
    )


if __name__ == "__main__":
    main()
