"""CLI for Quantum-Network Entanglement Capacity & CAT(0) Feasibility Checker (`qcat0`)."""

from __future__ import annotations

import argparse
import json
import pathlib
from typing import List, Optional

import numpy as np

from .cat0_cone import audit_metric_cat0
from .models import QuantumNetwork, get_topology, list_topologies
from .solvers import check_slocc_feasibility, solve_covering_capacity_hierarchy


def _load_net(spec: str) -> QuantumNetwork:
    p = pathlib.Path(spec)
    if p.exists() and p.is_file():
        return QuantumNetwork.from_json_file(p)
    return get_topology(spec)


def cmd_list(args: argparse.Namespace) -> int:
    for name in list_topologies():
        net = get_topology(name)
        print(
            f"  {name:<22} | n={net.num_parties:<2} | "
            f"src={len(net.source_eprs)} EPR (+{len(net.source_ghz)} GHZ) | "
            f"tgt={len(net.target_eprs)} EPR | {net.description}"
        )
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    net = _load_net(args.network)
    cov = solve_covering_capacity_hierarchy(net)
    feas = check_slocc_feasibility(net, run_covering_analysis=False)
    feas.covering_ebit_budget_cat0 = cov.ebit_budget_cat0
    feas.covering_feasible_with_l2_cover = net.total_source_ebits + 1e-5 >= cov.ebit_budget_cat0

    payload = {
        "network": net.to_dict(),
        "covering_capacity": cov.to_dict(),
        "slocc_feasibility": feas.to_dict(),
    }
    if args.as_json:
        print(json.dumps(payload, indent=2))
        return 0

    print(f"=== Quantum-Network CAT(0) Feasibility Check: {net.name} (n={net.num_parties}) ===")
    if net.description:
        print(f"Description: {net.description}")
    print(f"Source ebits: {net.total_source_ebits:.3f} | Target ebits: {net.total_target_ebits:.3f}")
    print(f"Solver:       CVXPY ({cov.solver}) | BN constraints: {cov.active_bn_constraints} (rounds={cov.cutting_plane_rounds})")
    print()
    print("  1. Asymptotic L2-Covering Capacity Hierarchy (Theorem C.1 + Strassen Duality):")
    print(f"     Metric Cone (triangle only):     rho={cov.rho_metric:.5f}  ->  budget <= {cov.ebit_budget_metric:.4f} ebits")
    print(f"     CAT(0) Cone (Berg-Nikolaev):     rho={cov.rho_cat0:.5f}  ->  budget <= {cov.ebit_budget_cat0:.4f} ebits")
    print(f"     Euclidean Cone (Schoenberg SDP): rho={cov.rho_euclidean:.5f}  ->  budget <= {cov.ebit_budget_euclidean:.4f} ebits")
    print(f"     CAT(0) compression vs triangle:  {cov.cat0_compression_ratio:.4f}x  (witness max BN viol={cov.witness_cat0_max_bn_violation:.2e})")
    if cov.euclidean_vs_cat0_ratio > 1.001:
        print(f"     Non-Euclidean CAT(0) gap vs R^d: {cov.euclidean_vs_cat0_ratio:.4f}x (hyperbolic/tree/rank strictly looser than flat!)")
    print()
    print("  2. Single-Restriction Asymptotic SLOCC Outer Bounds:")
    print(f"     Verdict:             {feas.verdict}")
    print(f"     Min bipartition cut: {feas.min_cut_ratio:.4f}  (cut={feas.worst_cut_partition})")
    print(f"     Metric LP bound:     {feas.metric_lp_ratio:.4f}")
    print(f"     CAT(0) spectral min: {feas.cat0_spectral_ratio:.4f}")
    for note in feas.notes:
        print(f"     Note: {note}")
    return 0


def cmd_benchmark(args: argparse.Namespace) -> int:
    names = args.topologies or list_topologies()
    results = []
    if not args.as_json:
        print(
            f"{'Topology':<22} | {'n':>2} | {'rho_M':>7} | {'rho_CAT0':>8} | {'rho_Euc':>7} | "
            f"{'CAT0 Gain':>9} | {'CutRat':>6} | {'Verdict'}"
        )
        print("-" * 102)
    for name in names:
        net = get_topology(name)
        cov = solve_covering_capacity_hierarchy(net)
        feas = check_slocc_feasibility(net, run_covering_analysis=False)
        results.append({"covering": cov.to_dict(), "feasibility": feas.to_dict()})
        if not args.as_json:
            print(
                f"{name:<22} | {net.num_parties:>2} | {cov.rho_metric:>7.4f} | {cov.rho_cat0:>8.4f} | "
                f"{cov.rho_euclidean:>7.4f} | {cov.cat0_compression_ratio:>8.4f}x | "
                f"{feas.min_cut_ratio:>6.3f} | {feas.verdict}"
            )
    if args.as_json:
        print(json.dumps(results, indent=2))
    return 0


def cmd_audit_metric(args: argparse.Namespace) -> int:
    raw = json.loads(args.matrix_json.read_text(encoding="utf-8"))
    D = np.asarray(raw, dtype=float)
    res = audit_metric_cat0(D, compute_projections=args.project)
    if args.as_json:
        print(json.dumps(res.to_dict(), indent=2))
    else:
        print(json.dumps(res.to_dict(), indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="qcat0",
        description="Quantum-Network Entanglement Capacity & CAT(0) Feasibility Checker (Theorem C.1 + CVXPY)",
    )
    sub = p.add_subparsers(dest="command", required=True)

    p_ls = sub.add_parser("list", help="List built-in quantum network topologies")
    p_ls.set_defaults(func=cmd_list)

    p_chk = sub.add_parser("check", help="Check a built-in topology name or custom JSON network file")
    p_chk.add_argument("network", help="Topology name (e.g. C4_crossing, hypercube_Q3) or path to JSON")
    p_chk.add_argument("--json", action="store_true", dest="as_json")
    p_chk.set_defaults(func=cmd_check)

    p_bm = sub.add_parser("benchmark", help="Run CVXPY SOCP/SDP benchmark across all canonical topologies")
    p_bm.add_argument("topologies", nargs="*", help="Optional subset of topology names")
    p_bm.add_argument("--json", action="store_true", dest="as_json")
    p_bm.set_defaults(func=cmd_benchmark)

    p_am = sub.add_parser("audit-metric", help="Audit an n x n spectral distance matrix JSON for CAT(0) & Euclidean laws")
    p_am.add_argument("matrix_json", type=pathlib.Path)
    p_am.add_argument("--project", action="store_true", help="Compute CVXPY SOCP/SDP projection distances")
    p_am.add_argument("--json", action="store_true", dest="as_json")
    p_am.set_defaults(func=cmd_audit_metric)

    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
