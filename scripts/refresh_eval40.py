#!/usr/bin/env python3
"""Refresh the checked-in Eval-40 publication from a clean source revision."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lean-bin", type=Path, help="Directory containing lean and lake")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    status = subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=normal"], cwd=repo, text=True
    )
    if status:
        parser.error("refresh requires a clean working tree to record reliable source provenance")
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    with tempfile.TemporaryDirectory(prefix="pcvh-publish-eval40-") as tmp:
        report = Path(tmp) / "eval_results_40.json"
        dashboard = Path(tmp) / "eval_dashboard.html"
        args_list = [
            sys.executable, "-m", "pcvh", "eval", "--source-revision", revision,
            "--out-json", str(report), "--out-html", str(dashboard),
        ]
        if args.lean_bin:
            args_list += ["--lean-bin", str(args.lean_bin.resolve())]
        subprocess.run(
            args_list, cwd=repo / "pcvh", check=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        data = json.loads(report.read_text(encoding="utf-8"))
        if (
            data["schema"] != "pcvh.eval40.v2"
            or data["run_metadata"]["source_revision"] != revision
            or data["sound_palomar_verified"] != data["sound_tasks"]
            or data["buggy_caught_stage2"] != data["buggy_tasks"]
            or data["sound_false_refutations"] != 0
        ):
            raise SystemExit("Eval-40 did not clear the snapshot publication checks")
        if (
            subprocess.check_output(
                ["git", "status", "--porcelain", "--untracked-files=normal"], cwd=repo, text=True
            )
            or subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
            != revision
        ):
            raise SystemExit("Source checkout changed during Eval-40; published files not replaced")
        shutil.copyfile(report, repo / "pcvh" / report.name)
        shutil.copyfile(dashboard, repo / "pcvh" / "pcvh" / "studio" / dashboard.name)
    print(f"Refreshed the published Eval-40 snapshot from {revision}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
