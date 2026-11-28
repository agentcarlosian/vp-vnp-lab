"""Review a deterministic transcript from a trusted reference project against its Lean spec."""

import argparse
import hashlib
from pathlib import Path
import tempfile
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pcvh"))
from pcvh.config import load_spec_config
from pcvh.tcb.conformance import produce, replay, stage_oracle
from pcvh.tcb.manifest import pin_tcb_manifest, stage_project_files, verify_tcb_manifest
from pcvh.tcb.palomar_gate import resolve_lean_bin


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path, help="reviewed reference implementation to execute locally")
    parser.add_argument("--traces", type=int, required=True, help="independently expected number of cases")
    parser.add_argument("--lean-bin", type=Path)
    args = parser.parse_args()
    if args.traces < 1:
        parser.error("the reference must contain at least one case")
    source = args.reference.resolve()
    lean_bin = resolve_lean_bin(source, args.lean_bin)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "reference"
        stage_project_files(source, root, include_lake_manifest=True)
        cfg = load_spec_config(root)
        if not cfg.conformance_command:
            parser.error("reference has no conformance command")
        pin_tcb_manifest(cfg, save_snapshot=False)
        oracle = Path(tmp) / "oracle"
        stage_oracle(root, verify_tcb_manifest(cfg), oracle)
        records = produce(cfg, lean_bin).replace(b"\r\n", b"\n")
        trusted = load_spec_config(oracle)
        trusted.conformance_traces = args.traces
        trusted.conformance_sha256 = hashlib.sha256(records).hexdigest()
        print(replay(trusted, records, lean_bin))
        print(f"traces = {trusted.conformance_traces}")
        print(f'transcript_sha256 = "{trusted.conformance_sha256}"')


if __name__ == "__main__":
    main()
