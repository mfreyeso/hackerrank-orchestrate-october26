"""Starter entry point `python3 code/main.py` delegating to `deletion_audit.cli`."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from deletion_audit.cli import run_command, usage_command  # noqa: E402


def main() -> None:
    """Run the full 518-case audit and write output.csv + usage_report.md."""
    run_command(split="full", output=ROOT_DIR / "output.csv")
    usage_command(report=ROOT_DIR / "evaluation" / "usage_report.md", total_requests=518)


if __name__ == "__main__":
    main()
