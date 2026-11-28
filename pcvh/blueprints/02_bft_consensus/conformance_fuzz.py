"""Differential Conformance Bridge: compares Python `prod_bft.py` against Lean 4 `Specs.Bft.Statement`."""

from __future__ import annotations

import argparse
import os
import pathlib
import random
import shutil
import subprocess
import sys
import tempfile
from typing import List, Literal

from prod_bft import MerkleNode, ValidatorVote, build_merkle_proof, check_bft_quorums, verify_merkle_proof


def _resolve_lean_bin(start: pathlib.Path) -> str:
    exe = "lake.exe" if os.name == "nt" else "lake"
    if os.environ.get("PCVH_LEAN_BIN"):
        return os.environ["PCVH_LEAN_BIN"]
    candidates = []
    if os.environ.get("ELAN_HOME"):
        candidates.append(pathlib.Path(os.environ["ELAN_HOME"]))
    for anc in [start, *start.parents[:6]]:
        if (anc / ".elan").exists():
            candidates.append(anc / ".elan")
    if (pathlib.Path.home() / ".elan").exists():
        candidates.append(pathlib.Path.home() / ".elan")
    for elan in candidates:
        tcs = elan / "toolchains"
        if tcs.exists():
            pref = tcs / "leanprover--lean4---v4.33.1" / "bin"
            if (pref / exe).exists():
                return str(pref)
            for child in sorted(tcs.iterdir(), reverse=True):
                if (child / "bin" / exe).exists():
                    return str(child / "bin")
    w = shutil.which("lake")
    if w:
        return str(pathlib.Path(w).parent)
    raise FileNotFoundError("Could not locate Lean 4 `lake` binary; set PCVH_LEAN_BIN or install via elan.")

_LEAN_RUNNER = pathlib.Path(__file__).with_name("conformance-oracle.lean.in").read_text(encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--traces", type=int, default=500)
    parser.add_argument("--seed", type=int, default=202602)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    ws = pathlib.Path(os.environ.get("PCVH_OVERLAY_WS", str(pathlib.Path(__file__).resolve().parent)))
    lean_bin = _resolve_lean_bin(pathlib.Path(__file__).resolve().parent)
    lake_exe = os.path.join(lean_bin, "lake.exe" if os.name == "nt" else "lake")
    env = os.environ.copy()
    env["PATH"] = lean_bin + os.pathsep + env.get("PATH", "")

    rows: List[str] = []
    for _ in range(args.traces):
        n = rng.choice([4, 7, 10])
        f_max = (n - 1) // 3
        f_cnt = rng.randint(0, f_max)
        byz_idx = set(rng.sample(range(n), f_cnt))
        q_size = (2 * n) // 3 + 1
        q1_idx = set(rng.sample(range(n), q_size))
        q2_idx = set(rng.sample(range(n), q_size))
        votes = [ValidatorVote(i in byz_idx, i in q1_idx, i in q2_idx) for i in range(n)]
        f, q1, q2, _ = check_bft_quorums(votes)

        leaves = [rng.randint(0, 500) for _ in range(4)]
        tree = MerkleNode(
            left=MerkleNode(left=MerkleNode(val=leaves[0]), right=MerkleNode(val=leaves[1])),
            right=MerkleNode(left=MerkleNode(val=leaves[2]), right=MerkleNode(val=leaves[3])),
        )
        dirs: List[Literal["L", "R"]] = [rng.choice(["L", "R"]), rng.choice(["L", "R"])]
        v, pf = build_merkle_proof(tree, dirs)
        root = verify_merkle_proof(v, pf)
        assert root == tree.root()

        s_votes = ";".join(f"{int(x.is_byz)},{int(x.in_q1)},{int(x.in_q2)}" for x in votes)
        s_leaves = ",".join(str(x) for x in leaves)
        s_dirs = ",".join(dirs)
        rows.append(f"{s_votes}|{f}|{q1}|{q2}|{s_leaves}|{s_dirs}|{v}|{root}")

    if os.environ.get("PCVH_EMIT_TRACES") == "1":
        sys.stdout.write("\n".join(rows) + "\n")
        return 0

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as tf:
        tf.write("\n".join(rows) + "\n")
        data_fp = pathlib.Path(tf.name)

    try:
        script = _LEAN_RUNNER.replace("{DATA_FILE}", data_fp.as_posix())
        proc = subprocess.run(
            [lake_exe, "env", "lean", "--stdin"],
            input=script,
            cwd=str(ws),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if proc.returncode != 0:
            print(proc.stdout, proc.stderr, file=sys.stderr)
            return proc.returncode
        print(proc.stdout.strip())
        return 0
    finally:
        try:
            data_fp.unlink()
        except OSError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
