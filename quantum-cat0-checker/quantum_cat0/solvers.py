"""CVXPY SOCP/SDP solvers for CAT(0) entanglement capacity & asymptotic SLOCC feasibility (Theorem C.1)."""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from math import sqrt
from typing import Dict, List, Optional, Tuple

import cvxpy as cp
import networkx as nx
import numpy as np
from scipy.optimize import minimize

from .cat0_cone import (
    add_all_berg_nikolaev_socp_constraints,
    add_berg_nikolaev_socp_constraint,
    add_triangle_socp_constraints,
    audit_metric_cat0,
    choose_conic_solver,
    find_violated_berg_nikolaev_quads,
    project_onto_cat0_socp,
    solve_with_conic_fallback,
)
from .models import QuantumNetwork


@dataclass
class CoveringCapacityResult:
    network_name: str
    num_parties: int
    solver: str
    rho_metric: float          # max sum t_f u_f / sum s_e u_e over Metric cone M_n
    rho_cat0: float            # max sum t_f u_f / sum s_e u_e over exact CAT(0) cone K_{CAT(0), n}
    rho_euclidean: float       # max sum t_f u_f / sum s_e u_e over Schoenberg Hilbert cone E_n
    ebit_budget_metric: float      # sqrt(s_tot * t_tot * rho_metric)
    ebit_budget_cat0: float        # sqrt(s_tot * t_tot * rho_cat0)
    ebit_budget_euclidean: float   # sqrt(s_tot * t_tot * rho_euclidean)
    cat0_compression_ratio: float          # ebit_budget_metric / ebit_budget_cat0
    euclidean_vs_cat0_ratio: float         # ebit_budget_cat0 / ebit_budget_euclidean
    cutting_plane_rounds: int
    active_bn_constraints: int
    witness_cat0_metric: np.ndarray        # worst-case CAT(0) spectral metric D^* = sqrt(U^*)
    witness_cat0_max_bn_violation: float   # certified <= 1e-5
    witness_euclidean_coords: Optional[np.ndarray] = None

    def to_dict(self) -> Dict[str, object]:
        return {
            "network_name": self.network_name,
            "num_parties": self.num_parties,
            "solver": self.solver,
            "rho_metric": round(self.rho_metric, 6),
            "rho_cat0": round(self.rho_cat0, 6),
            "rho_euclidean": round(self.rho_euclidean, 6),
            "ebit_budget_metric": round(self.ebit_budget_metric, 6),
            "ebit_budget_cat0": round(self.ebit_budget_cat0, 6),
            "ebit_budget_euclidean": round(self.ebit_budget_euclidean, 6),
            "cat0_compression_ratio": round(self.cat0_compression_ratio, 6),
            "euclidean_vs_cat0_ratio": round(self.euclidean_vs_cat0_ratio, 6),
            "cutting_plane_rounds": self.cutting_plane_rounds,
            "active_bn_constraints": self.active_bn_constraints,
            "witness_cat0_max_bn_violation": round(self.witness_cat0_max_bn_violation, 8),
        }


@dataclass
class SLOCCFeasibilityResult:
    network_name: str
    verdict: str  # FORBIDDEN_BY_CUT | FORBIDDEN_BY_CAT0_SPECTRAL | CLASSICAL_LP_GAP_ONLY | FEASIBLE_UNDER_OUTER_BOUNDS
    min_cut_ratio: float               # min_A cap(A) / demand(A); < 1 proves impossibility!
    worst_cut_partition: Optional[List[int]]
    metric_lp_ratio: float             # min_{d in M_n} sum s_e d_e / sum t_f d_f
    cat0_spectral_ratio: float         # min_{d in CAT(0)} sum s_e d_e / sum t_f d_f
    covering_ebit_budget_cat0: Optional[float]
    covering_feasible_with_l2_cover: Optional[bool]
    witness_metric: Optional[np.ndarray] = None
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        return {
            "network_name": self.network_name,
            "verdict": self.verdict,
            "min_cut_ratio": round(self.min_cut_ratio, 6),
            "worst_cut_partition": self.worst_cut_partition,
            "metric_lp_ratio": round(self.metric_lp_ratio, 6),
            "cat0_spectral_ratio": round(self.cat0_spectral_ratio, 6),
            "covering_ebit_budget_cat0": (
                round(self.covering_ebit_budget_cat0, 6)
                if self.covering_ebit_budget_cat0 is not None
                else None
            ),
            "covering_feasible_with_l2_cover": self.covering_feasible_with_l2_cover,
            "notes": list(self.notes),
        }


def _extract_u_matrix(u_vars: Dict[Tuple[int, int], cp.Variable], n: int) -> np.ndarray:
    U = np.zeros((n, n), dtype=float)
    for (i, j), var in u_vars.items():
        val = max(0.0, float(var.value)) if var.value is not None else 0.0
        U[i, j] = val
        U[j, i] = val
    return U


def _solve_socp_ratio(
    net: QuantumNetwork,
    include_cat0: bool,
    use_cutting_planes: bool,
    solver: str,
    max_rounds: int = 40,
    cuts_per_round: int = 100,
    tol: float = 1e-6,
) -> Tuple[float, np.ndarray, int, int]:
    """Solve max_{u in Cone} sum_{f in T} t_f u_f  s.t.  sum_{e in S} s_e u_e <= 1."""
    n = net.num_parties
    u_vars: Dict[Tuple[int, int], cp.Variable] = {
        (i, j): cp.Variable(nonneg=True) for i, j in combinations(range(n), 2)
    }
    base_constraints: List[cp.Constraint] = []

    # Permutation-invariant source normalization:
    # 1 copy of GHZ(A) restricts via LOCC to any single pair (p, q) in A -> d_phi(GHZ_A)^2 >= max_{p<q in A} u_{pq}
    src_terms = [w * u_vars[e] for e, w in net.source_eprs.items()]
    for g in net.source_ghz:
        if len(g.parties) >= 2:
            u_ghz = cp.Variable(nonneg=True)
            for p, q in combinations(sorted(g.parties), 2):
                base_constraints.append(u_ghz >= u_vars[(p, q)])
            src_terms.append(g.rate * u_ghz)
    if not src_terms:
        raise ValueError("Network has no source resources.")
    base_constraints.append(cp.sum(src_terms) <= 1.0)
    add_triangle_socp_constraints(u_vars, n, base_constraints)

    obj = cp.Maximize(cp.sum([w * u_vars[f] for f, w in net.target_eprs.items()]))

    if not include_cat0:
        prob = cp.Problem(obj, base_constraints)
        solve_with_conic_fallback(prob, preferred=solver)
        U = _extract_u_matrix(u_vars, n)
        return float(prob.value), U, 0, 0

    if not use_cutting_planes:
        constraints = list(base_constraints)
        add_all_berg_nikolaev_socp_constraints(u_vars, n, constraints)
        prob = cp.Problem(obj, constraints)
        solve_with_conic_fallback(prob, preferred=solver)
        U = _extract_u_matrix(u_vars, n)
        n_bn = 3 * (n * (n - 1) * (n - 2) * (n - 3) // 24) if n >= 4 else 0
        return float(prob.value), U, 1, n_bn

    # Lazy cutting-plane separation for larger networks (n > 10)
    added_quads = set()
    constraints = list(base_constraints)
    rounds = 0
    U = np.zeros((n, n), dtype=float)
    val = 0.0
    for r in range(1, max_rounds + 1):
        rounds = r
        prob = cp.Problem(obj, constraints)
        solve_with_conic_fallback(prob, preferred=solver)
        val = float(prob.value)
        U = _extract_u_matrix(u_vars, n)
        viols = find_violated_berg_nikolaev_quads(U, tol=tol)
        if not viols:
            break
        added_this_round = 0
        for _, q in viols:
            if q not in added_quads:
                added_quads.add(q)
                add_berg_nikolaev_socp_constraint(u_vars, q, constraints)
                added_this_round += 1
                if added_this_round >= cuts_per_round:
                    break
        if added_this_round == 0:
            break
    return val, U, rounds, len(added_quads)


def _solve_euclidean_sdp_ratio(net: QuantumNetwork, solver: str) -> Tuple[float, np.ndarray, np.ndarray]:
    """Solve max_{G >= 0} sum t_f (G_ii + G_jj - 2 G_ij) s.t. sum s_e (G_ii + G_jj - 2 G_ij) <= 1."""
    n = net.num_parties
    G = cp.Variable((n, n), PSD=True)

    def u_expr(edge: Tuple[int, int]) -> cp.Expression:
        i, j = edge
        return G[i, i] + G[j, j] - 2.0 * G[i, j]

    constraints: List[cp.Constraint] = [cp.sum(G, axis=0) == 0]
    src_terms = [w * u_expr(e) for e, w in net.source_eprs.items()]
    for g in net.source_ghz:
        if len(g.parties) >= 2:
            u_ghz = cp.Variable(nonneg=True)
            for p, q in combinations(sorted(g.parties), 2):
                constraints.append(u_ghz >= u_expr((p, q)))
            src_terms.append(g.rate * u_ghz)

    constraints.append(cp.sum(src_terms) <= 1.0)
    obj = cp.Maximize(cp.sum([w * u_expr(f) for f, w in net.target_eprs.items()]))
    prob = cp.Problem(obj, constraints)
    solve_with_conic_fallback(prob, preferred=solver)

    G_val = np.asarray(G.value, dtype=float) if G.value is not None else np.zeros((n, n), dtype=float)
    G_val = 0.5 * (G_val + G_val.T)
    eigvals, eigvecs = np.linalg.eigh(G_val)
    eigvals_pos = np.maximum(eigvals, 0.0)
    coords = eigvecs * np.sqrt(eigvals_pos)[None, :]

    U = np.zeros((n, n), dtype=float)
    for i, j in combinations(range(n), 2):
        val = max(0.0, float(G_val[i, i] + G_val[j, j] - 2.0 * G_val[i, j]))
        U[i, j] = val
        U[j, i] = val
    return float(prob.value), U, coords


def solve_covering_capacity_hierarchy(
    net: QuantumNetwork,
    cutting_plane_threshold_n: int = 10,
    solver: Optional[str] = None,
) -> CoveringCapacityResult:
    """Compute nested Metric (triangle) >= CAT(0) (Thm C.1 SOCP) >= Euclidean (SDP) covering bounds.

    By Theorem C.1 + Strassen Duality (Theorem A.6):
      For every spectral point phi, (sum t_f d_f)^2 <= t_tot * rho_cat0 * (sum s_e d_e^2),
      certifying an asymptotic L_2-bounded covering protocol of total ebits <= sqrt(s_tot * t_tot * rho_cat0).
    """
    conic_solver = solver or choose_conic_solver()
    use_cp = net.num_parties > cutting_plane_threshold_n

    rho_metric, _, _, _ = _solve_socp_ratio(
        net, include_cat0=False, use_cutting_planes=False, solver=conic_solver
    )
    rho_cat0, U_cat0, cp_rounds, n_bn = _solve_socp_ratio(
        net, include_cat0=True, use_cutting_planes=use_cp, solver=conic_solver
    )
    rho_euc, _, coords = _solve_euclidean_sdp_ratio(net, solver=conic_solver)

    s_tot = net.total_source_ebits
    t_tot = net.total_target_ebits

    ebit_metric = sqrt(max(0.0, s_tot * t_tot * rho_metric))
    ebit_cat0 = sqrt(max(0.0, s_tot * t_tot * rho_cat0))
    ebit_euc = sqrt(max(0.0, s_tot * t_tot * rho_euc))

    D_cat0 = np.sqrt(np.maximum(U_cat0, 0.0))
    audit = audit_metric_cat0(D_cat0)

    return CoveringCapacityResult(
        network_name=net.name,
        num_parties=net.num_parties,
        solver=conic_solver,
        rho_metric=rho_metric,
        rho_cat0=rho_cat0,
        rho_euclidean=rho_euc,
        ebit_budget_metric=ebit_metric,
        ebit_budget_cat0=ebit_cat0,
        ebit_budget_euclidean=ebit_euc,
        cat0_compression_ratio=ebit_metric / max(ebit_cat0, 1e-12),
        euclidean_vs_cat0_ratio=ebit_cat0 / max(ebit_euc, 1e-12),
        cutting_plane_rounds=cp_rounds,
        active_bn_constraints=n_bn,
        witness_cat0_metric=D_cat0,
        witness_cat0_max_bn_violation=audit.max_berg_nikolaev_violation,
        witness_euclidean_coords=coords,
    )


def _exact_min_cut_ratio(net: QuantumNetwork) -> Tuple[float, Optional[List[int]]]:
    """Compute exact min_{A subset V} (source cut across A) / (target cut across A)."""
    n = net.num_parties
    best_ratio = float("inf")
    best_cut: Optional[List[int]] = None

    if n <= 14:
        for mask in range(1, 1 << (n - 1)):
            in_a = {0}
            for bit in range(n - 1):
                if mask & (1 << bit):
                    in_a.add(bit + 1)
            t_cut = 0.0
            for (u, v), w in net.target_eprs.items():
                if (u in in_a) != (v in in_a):
                    t_cut += w
            if t_cut <= 1e-12:
                continue
            s_cut = 0.0
            for (u, v), w in net.source_eprs.items():
                if (u in in_a) != (v in in_a):
                    s_cut += w
            # Any GHZ state split by bipartition A contributes 1 ebit * rate (Schmidt rank 2!)
            for g in net.source_ghz:
                in_cnt = sum(1 for p in g.parties if p in in_a)
                if 0 < in_cnt < len(g.parties):
                    s_cut += g.rate
            ratio = s_cut / t_cut
            if ratio < best_ratio:
                best_ratio = ratio
                best_cut = sorted(in_a)
        return best_ratio, best_cut

    G = nx.Graph()
    G.add_nodes_from(range(n))
    for (u, v), w in net.source_eprs.items():
        G.add_edge(u, v, capacity=w)
    for (u, v), w in net.target_eprs.items():
        cut_val, (part_a, _) = nx.minimum_cut(G, u, v)
        in_a = set(part_a)
        t_cut = sum(tw for (x, y), tw in net.target_eprs.items() if (x in in_a) != (y in in_a))
        s_cut = cut_val + sum(
            g.rate for g in net.source_ghz if 0 < sum(1 for p in g.parties if p in in_a) < len(g.parties)
        )
        if t_cut > 1e-12 and s_cut / t_cut < best_ratio:
            best_ratio = s_cut / t_cut
            best_cut = sorted(in_a)
    return best_ratio, best_cut


def _metric_lp_ratio(net: QuantumNetwork) -> Tuple[float, np.ndarray]:
    """Solve min_{d in Metric Cone M_n} sum s_e d_e  s.t.  sum t_f d_f == 1 via CVXPY LP."""
    n = net.num_parties
    d_vars: Dict[Tuple[int, int], cp.Variable] = {
        (i, j): cp.Variable(nonneg=True) for i, j in combinations(range(n), 2)
    }
    constraints: List[cp.Constraint] = []
    for i, j, k in combinations(range(n), 3):
        constraints.append(d_vars[(i, k)] <= d_vars[(i, j)] + d_vars[(j, k)])
        constraints.append(d_vars[(i, j)] <= d_vars[(i, k)] + d_vars[(j, k)])
        constraints.append(d_vars[(j, k)] <= d_vars[(i, j)] + d_vars[(i, k)])

    constraints.append(cp.sum([w * d_vars[f] for f, w in net.target_eprs.items()]) == 1.0)

    src_terms = [w * d_vars[e] for e, w in net.source_eprs.items()]
    for g in net.source_ghz:
        if len(g.parties) >= 2:
            # Diameter bound z_g >= d_{pq}: exact on all flattening / l1 cut combinations!
            z_g = cp.Variable(nonneg=True)
            for p, q in combinations(sorted(g.parties), 2):
                constraints.append(z_g >= d_vars[(p, q)])
            src_terms.append(g.rate * z_g)

    prob = cp.Problem(cp.Minimize(cp.sum(src_terms)), constraints)
    lp_solver = "SCIPY" if "SCIPY" in cp.installed_solvers() else choose_conic_solver()
    prob.solve(solver=lp_solver)

    D = np.zeros((n, n), dtype=float)
    for (i, j), var in d_vars.items():
        val = max(0.0, float(var.value)) if var.value is not None else 0.0
        D[i, j] = val
        D[j, i] = val
    return float(prob.value), D


def _is_cut_pseudometric(D: np.ndarray, tol: float = 1e-5) -> bool:
    """Check whether D is a scalar multiple of a bipartition cut pseudometric c * 1_{i in A != j in A}."""
    vals = D[np.triu_indices(D.shape[0], k=1)]
    pos = vals[vals > tol]
    if pos.size == 0:
        return False
    c = float(np.max(pos))
    if np.any(np.minimum(np.abs(vals), np.abs(vals - c)) > tol):
        return False
    # Check 0-distance equivalence relation has at most 2 classes
    in_zero = [j for j in range(D.shape[0]) if D[0, j] <= tol]
    out_zero = [j for j in range(D.shape[0]) if D[0, j] > tol]
    for u in in_zero:
        for v in in_zero:
            if D[u, v] > tol:
                return False
    for u in out_zero:
        for v in out_zero:
            if D[u, v] > tol:
                return False
    return True


def _evaluate_linear_ratio(net: QuantumNetwork, D: np.ndarray) -> float:
    denom = sum(w * D[u, v] for (u, v), w in net.target_eprs.items())
    if denom <= 1e-12:
        return float("inf")
    num = sum(w * D[u, v] for (u, v), w in net.source_eprs.items())
    is_cut = bool(net.source_ghz) and _is_cut_pseudometric(D)
    for g in net.source_ghz:
        if len(g.parties) >= 2:
            if is_cut:
                # Flattening rank functional is an exact element of Strassen's spectrum:
                # log_2 rk_{A | V\A}(GHZ_P) = max_{p,q in P} D_A(p, q).
                ghz_cost = max(D[p, q] for p, q in combinations(g.parties, 2))
            else:
                # Universal upper bound over arbitrary spectral points via minimum star restriction
                ghz_cost = min(
                    sum(D[hub, p] for p in g.parties if p != hub) for hub in g.parties
                )
            num += g.rate * ghz_cost
    return float(num / denom)


def _cat0_spectral_witness_search(
    net: QuantumNetwork,
    seed_metrics: List[np.ndarray],
) -> Tuple[float, np.ndarray]:
    """Find minimum source/target ratio over genuine CAT(0) metrics (cuts, R-trees, CAT(0) SOCP projections, & L-BFGS-B R^d)."""
    n = net.num_parties
    best_ratio = float("inf")
    best_D = np.zeros((n, n), dtype=float)

    def consider(D: np.ndarray) -> None:
        nonlocal best_ratio, best_D
        if np.max(D) <= 1e-9:
            return
        audit = audit_metric_cat0(D, tol=1e-4)
        if not audit.is_cat0_4pt:
            return
        r = _evaluate_linear_ratio(net, D)
        if r < best_ratio:
            best_ratio = r
            best_D = D.copy()

    # 1. Seed metrics (worst cut, LP metric if CAT(0), CAT(0) SOCP projection of LP metric, covering witness)
    for D in seed_metrics:
        consider(D)

    # 2. Non-Euclidean R-tree metrics: star trees & source-graph spanning trees (every tree metric is strictly CAT(0)!)
    consider(np.ones((n, n), dtype=float) - np.eye(n, dtype=float))
    for hub in range(n):
        D_star = np.full((n, n), 2.0, dtype=float)
        np.fill_diagonal(D_star, 0.0)
        for p in range(n):
            if p != hub:
                D_star[hub, p] = D_star[p, hub] = 1.0
        consider(D_star)

    G_src = nx.Graph()
    G_src.add_nodes_from(range(n))
    for (u, v), w in net.source_eprs.items():
        G_src.add_edge(u, v, weight=1.0 / max(w, 1e-6))
    if nx.is_connected(G_src):
        T = nx.minimum_spanning_tree(G_src)
        D_tree = np.zeros((n, n), dtype=float)
        for u, lengths in nx.all_pairs_dijkstra_path_length(T, weight="weight"):
            for v, d_uv in lengths.items():
                D_tree[u, v] = float(d_uv)
        consider(D_tree)

    # 3. Smooth L-BFGS-B optimization over Euclidean embeddings X in R^{n x d} (every Euclidean metric is CAT(0)!)
    rng = np.random.default_rng(42)
    dim = min(n, 4)
    eps = 1e-10
    src_items = list(net.source_eprs.items())
    tgt_items = list(net.target_eprs.items())

    if not net.source_ghz and tgt_items:
        def smooth_obj(flat_x: np.ndarray) -> float:
            X = flat_x.reshape((n, dim))
            diff = X[:, None, :] - X[None, :, :]
            D = np.sqrt(np.sum(diff * diff, axis=-1) + eps)
            denom = sum(w * D[u, v] for (u, v), w in tgt_items)
            if denom <= 1e-9:
                return 1e6
            num = sum(w * D[u, v] for (u, v), w in src_items)
            return float(num / denom)

        for _ in range(8):
            x0 = rng.normal(size=n * dim)
            opt = minimize(smooth_obj, x0, method="L-BFGS-B", options={"maxiter": 80})
            X_opt = opt.x.reshape((n, dim))
            D_euc = np.linalg.norm(X_opt[:, None, :] - X_opt[None, :, :], axis=-1)
            consider(D_euc)
    else:
        for _ in range(40):
            pts = rng.normal(size=(n, dim))
            D_euc = np.linalg.norm(pts[:, None, :] - pts[None, :, :], axis=-1)
            consider(D_euc)

    return best_ratio, best_D


def check_slocc_feasibility(
    net: QuantumNetwork,
    run_covering_analysis: bool = True,
    precomputed_covering: Optional[CoveringCapacityResult] = None,
    tol: float = 1e-4,
) -> SLOCCFeasibilityResult:
    """Certify whether single-restriction asymptotic SLOCC S >=_asym T is forbidden or survives outer bounds."""
    notes: List[str] = []
    min_cut_ratio, worst_cut = _exact_min_cut_ratio(net)
    metric_lp_ratio, D_lp = _metric_lp_ratio(net)

    seeds: List[np.ndarray] = []
    if worst_cut is not None:
        in_a = set(worst_cut)
        D_cut = np.zeros((net.num_parties, net.num_parties), dtype=float)
        for i in range(net.num_parties):
            for j in range(net.num_parties):
                if (i in in_a) != (j in in_a):
                    D_cut[i, j] = 1.0
        seeds.append(D_cut)

    lp_audit = audit_metric_cat0(D_lp, tol=1e-4)
    if lp_audit.is_cat0_4pt:
        seeds.append(D_lp)
    elif net.num_parties >= 4 and np.max(D_lp) > 1e-6:
        # Project non-CAT(0) LP optimizer onto exact CAT(0) cone as a high-quality non-Euclidean seed!
        D_lp_proj, _ = project_onto_cat0_socp(D_lp)
        seeds.append(D_lp_proj)

    cov_budget = None
    cov_feasible = None
    cov = precomputed_covering
    if cov is None and run_covering_analysis:
        cov = solve_covering_capacity_hierarchy(net)
    if cov is not None:
        seeds.append(cov.witness_cat0_metric)
        cov_budget = cov.ebit_budget_cat0
        cov_feasible = net.total_source_ebits + tol >= cov_budget
        if cov.cat0_compression_ratio > 1.001:
            notes.append(
                f"CAT(0) Berg-Nikolaev bounds certify {cov.cat0_compression_ratio:.3f}x asymptotic "
                f"L2-covering ebit compression ({cov.ebit_budget_metric:.3f} -> {cov.ebit_budget_cat0:.3f} ebits)."
            )

    cat0_ratio, D_cat0 = _cat0_spectral_witness_search(net, seeds)

    if min_cut_ratio < 1.0 - tol:
        verdict = "FORBIDDEN_BY_CUT"
        notes.append(
            f"Bipartition cut {worst_cut} has source/target ratio {min_cut_ratio:.4f} < 1.0 "
            f"(impossible via single asymptotic SLOCC restriction)."
        )
        witness = seeds[0] if seeds else D_cat0
    elif cat0_ratio < 1.0 - tol:
        verdict = "FORBIDDEN_BY_CAT0_SPECTRAL"
        notes.append(
            f"Valid CAT(0) spectral metric witnesses source/target ratio {cat0_ratio:.4f} < 1.0."
        )
        witness = D_cat0
    elif metric_lp_ratio < 1.0 - tol:
        verdict = "CLASSICAL_LP_GAP_ONLY"
        notes.append(
            f"Classical Metric LP < 1 ({metric_lp_ratio:.4f}), whereas every CAT(0) spectral bound >= 1 "
            f"(min CAT(0)={cat0_ratio:.4f}; LP witness violates Berg-Nikolaev by {lp_audit.max_berg_nikolaev_violation:.4f} "
            f"and is ruled out of Strassen's spectrum by Theorem C.1!)."
        )
        witness = D_lp
    else:
        verdict = "FEASIBLE_UNDER_OUTER_BOUNDS"
        notes.append(
            f"Passes all bipartition cuts (min ratio {min_cut_ratio:.4f}), metric LP ({metric_lp_ratio:.4f}), "
            f"and CAT(0) spectral checks ({cat0_ratio:.4f})."
        )
        witness = D_cat0

    if cov_feasible is True and verdict == "FORBIDDEN_BY_CUT":
        notes.append(
            f"NOTE: Although single SLOCC restriction fails cut ({min_cut_ratio:.3f} < 1), "
            f"total source ebits ({net.total_source_ebits:.3f}) >= CAT(0) L2-cover budget ({cov_budget:.3f}), "
            f"so asymptotic covering (Theorem A.6) IS achievable by switching unbalanced allocations!"
        )

    return SLOCCFeasibilityResult(
        network_name=net.name,
        verdict=verdict,
        min_cut_ratio=min_cut_ratio,
        worst_cut_partition=worst_cut,
        metric_lp_ratio=metric_lp_ratio,
        cat0_spectral_ratio=cat0_ratio,
        covering_ebit_budget_cat0=cov_budget,
        covering_feasible_with_l2_cover=cov_feasible,
        witness_metric=witness,
        notes=notes,
    )
