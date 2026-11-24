"""Exact CAT(0) Berg-Nikolaev / Reshetnyak metric certification & CVXPY SOCP/SDP projections."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Dict, List, Optional, Tuple

import cvxpy as cp
import numpy as np


@dataclass
class MetricAuditResult:
    num_points: int
    is_valid_metric: bool
    max_triangle_violation: float
    is_cat0_4pt: bool
    max_berg_nikolaev_violation: float
    worst_quadruple: Optional[Tuple[int, int, int, int]]
    max_enflo_violation: float
    is_euclidean_embeddable: bool
    min_gram_eigenvalue: float
    cat0_projection_frobenius_dist: Optional[float] = None
    euclidean_projection_frobenius_dist: Optional[float] = None

    def to_dict(self) -> Dict[str, object]:
        return {
            "num_points": self.num_points,
            "is_valid_metric": self.is_valid_metric,
            "max_triangle_violation": round(self.max_triangle_violation, 8),
            "is_cat0_4pt": self.is_cat0_4pt,
            "max_berg_nikolaev_violation": round(self.max_berg_nikolaev_violation, 8),
            "worst_quadruple": list(self.worst_quadruple) if self.worst_quadruple else None,
            "max_enflo_violation": round(self.max_enflo_violation, 8),
            "is_euclidean_embeddable": self.is_euclidean_embeddable,
            "min_gram_eigenvalue": round(self.min_gram_eigenvalue, 8),
            "cat0_projection_frobenius_dist": (
                round(self.cat0_projection_frobenius_dist, 6)
                if self.cat0_projection_frobenius_dist is not None
                else None
            ),
            "euclidean_projection_frobenius_dist": (
                round(self.euclidean_projection_frobenius_dist, 6)
                if self.euclidean_projection_frobenius_dist is not None
                else None
            ),
        }


def choose_conic_solver() -> str:
    installed = set(cp.installed_solvers())
    for cand in ("CLARABEL", "SCS", "ECOS"):
        if cand in installed:
            return cand
    return next(iter(installed))


def schoenberg_gram_matrix(D: np.ndarray) -> np.ndarray:
    """Compute centered Gram matrix G = -1/2 J (D^2) J; D is Euclidean iff G is PSD."""
    n = D.shape[0]
    D2 = np.square(D)
    J = np.eye(n) - np.ones((n, n)) / n
    G = -0.5 * (J @ D2 @ J)
    return 0.5 * (G + G.T)


def find_violated_berg_nikolaev_quads(
    U: np.ndarray, tol: float = 1e-7
) -> List[Tuple[float, Tuple[int, int, int, int]]]:
    """Return all violated Berg-Nikolaev 4-tuples for squared-distance matrix U = D^2.

    For 4 distinct points {a,b,c,d}, the 3 Berg-Nikolaev inequalities are:
      |(U[a,c] + U[b,d]) - (U[a,d] + U[b,c])| <= 2 * sqrt(U[a,b] * U[c,d])
    (and the 2 other pairings obtained by permuting b,c,d).
    """
    n = U.shape[0]
    U_pos = np.maximum(U, 0.0)
    S = np.sqrt(U_pos)
    viols: List[Tuple[float, Tuple[int, int, int, int]]] = []
    for a, b, c, d in combinations(range(n), 4):
        # Pairing 1: pair (a,b) & (c,d) on RHS -> |(u_ac + u_bd) - (u_ad + u_bc)| <= 2 d_ab d_cd
        v1 = abs((U_pos[a, c] + U_pos[b, d]) - (U_pos[a, d] + U_pos[b, c])) - 2.0 * S[a, b] * S[c, d]
        if v1 > tol:
            viols.append((float(v1), (a, b, c, d)))
        # Pairing 2: pair (a,c) & (b,d) on RHS
        v2 = abs((U_pos[a, b] + U_pos[c, d]) - (U_pos[a, d] + U_pos[b, c])) - 2.0 * S[a, c] * S[b, d]
        if v2 > tol:
            viols.append((float(v2), (a, c, b, d)))
        # Pairing 3: pair (a,d) & (b,c) on RHS
        v3 = abs((U_pos[a, b] + U_pos[c, d]) - (U_pos[a, c] + U_pos[b, d])) - 2.0 * S[a, d] * S[b, c]
        if v3 > tol:
            viols.append((float(v3), (a, d, b, c)))
    viols.sort(key=lambda x: -x[0])
    return viols


def audit_metric_cat0(D: np.ndarray, tol: float = 1e-6, compute_projections: bool = False) -> MetricAuditResult:
    """Certify whether an n x n distance matrix D satisfies metric, CAT(0) Berg-Nikolaev, and Euclidean laws."""
    D = np.asarray(D, dtype=float)
    if D.ndim != 2 or D.shape[0] != D.shape[1]:
        raise ValueError("Distance matrix D must be square (n x n)")
    n = D.shape[0]
    D = 0.5 * (D + D.T)
    np.fill_diagonal(D, 0.0)

    # 1. Triangle inequality check
    max_tri = 0.0
    if np.min(D) < -tol:
        max_tri = max(max_tri, float(-np.min(D)))
    for i in range(n):
        for j in range(i + 1, n):
            for k in range(n):
                if k == i or k == j:
                    continue
                v = D[i, j] - (D[i, k] + D[k, j])
                if v > max_tri:
                    max_tri = float(v)

    # 2. Berg-Nikolaev quadrilateral cosine & Enflo roundness-2 check
    U = np.square(np.maximum(D, 0.0))
    viols = find_violated_berg_nikolaev_quads(U, tol=0.0)
    max_bn = viols[0][0] if viols else 0.0
    worst_q = viols[0][1] if viols else None

    max_enflo = 0.0
    for a, b, c, d in combinations(range(n), 4):
        # Three distinct 4-cycles on {a,b,c,d}:
        # (a-b-c-d): diag (ac, bd) vs sides (ab, bc, cd, da)
        for diag1, diag2, s1, s2, s3, s4 in (
            (U[a, c], U[b, d], U[a, b], U[b, c], U[c, d], U[d, a]),
            (U[a, b], U[c, d], U[a, c], U[c, b], U[b, d], U[d, a]),
            (U[a, d], U[b, c], U[a, b], U[b, d], U[d, c], U[c, a]),
        ):
            ev = float((diag1 + diag2) - (s1 + s2 + s3 + s4))
            if ev > max_enflo:
                max_enflo = ev

    # 3. Schoenberg Euclidean embeddability (G >= 0)
    G = schoenberg_gram_matrix(D)
    min_eig = float(np.min(np.linalg.eigvalsh(G))) if n > 0 else 0.0

    cat0_dist = None
    euc_dist = None
    if compute_projections and n >= 3:
        D_cat0, cat0_dist = project_onto_cat0_socp(D)
        _ = D_cat0
        _, euc_dist = project_onto_euclidean_sdp(D)

    return MetricAuditResult(
        num_points=n,
        is_valid_metric=(max_tri <= tol),
        max_triangle_violation=max_tri,
        is_cat0_4pt=(max_tri <= tol and max_bn <= tol),
        max_berg_nikolaev_violation=max_bn,
        worst_quadruple=worst_q,
        max_enflo_violation=max_enflo,
        is_euclidean_embeddable=(max_tri <= tol and min_eig >= -tol),
        min_gram_eigenvalue=min_eig,
        cat0_projection_frobenius_dist=cat0_dist,
        euclidean_projection_frobenius_dist=euc_dist,
    )


def add_triangle_socp_constraints(
    u_vars: Dict[Tuple[int, int], cp.Variable],
    n: int,
    constraints: List[cp.Constraint],
) -> None:
    """Add exact DCP-convex SOCP triangle inequalities u_ik - u_ij - u_jk <= 2 * geo_mean(u_ij, u_jk)."""
    for i, j, k in combinations(range(n), 3):
        u_ij = u_vars[(i, j)]
        u_jk = u_vars[(j, k)]
        u_ik = u_vars[(i, k)]
        constraints.append(u_ik - u_ij - u_jk <= 2.0 * cp.geo_mean(cp.hstack([u_ij, u_jk])))
        constraints.append(u_ij - u_ik - u_jk <= 2.0 * cp.geo_mean(cp.hstack([u_ik, u_jk])))
        constraints.append(u_jk - u_ij - u_ik <= 2.0 * cp.geo_mean(cp.hstack([u_ij, u_ik])))


def add_berg_nikolaev_socp_constraint(
    u_vars: Dict[Tuple[int, int], cp.Variable],
    quad: Tuple[int, int, int, int],
    constraints: List[cp.Constraint],
) -> None:
    """Add single exact Berg-Nikolaev SOCP constraint for ordered quadruple (a, b, c, d):
        |(u_ac + u_bd) - (u_ad + u_bc)| <= 2 * geo_mean(u_ab, u_cd)
    """
    a, b, c, d = quad

    def U(x: int, y: int) -> cp.Variable:
        return u_vars[(x, y) if x < y else (y, x)]

    lhs = (U(a, c) + U(b, d)) - (U(a, d) + U(b, c))
    rhs = 2.0 * cp.geo_mean(cp.hstack([U(a, b), U(c, d)]))
    constraints.append(lhs <= rhs)
    constraints.append(-lhs <= rhs)


def add_all_berg_nikolaev_socp_constraints(
    u_vars: Dict[Tuple[int, int], cp.Variable],
    n: int,
    constraints: List[cp.Constraint],
) -> None:
    """Add all 3 * C(n, 4) exact Berg-Nikolaev SOCP constraints for Theorem C.1."""
    for a, b, c, d in combinations(range(n), 4):
        add_berg_nikolaev_socp_constraint(u_vars, (a, b, c, d), constraints)
        add_berg_nikolaev_socp_constraint(u_vars, (a, c, b, d), constraints)
        add_berg_nikolaev_socp_constraint(u_vars, (a, d, b, c), constraints)


def project_onto_cat0_socp(D: np.ndarray) -> Tuple[np.ndarray, float]:
    """Project D^2 onto the exact CAT(0) 4-point cone K_{CAT(0), n} via CVXPY SOCP."""
    D = np.asarray(D, dtype=float)
    n = D.shape[0]
    U_target = np.square(np.maximum(0.5 * (D + D.T), 0.0))
    u_vars: Dict[Tuple[int, int], cp.Variable] = {
        (i, j): cp.Variable(nonneg=True) for i, j in combinations(range(n), 2)
    }
    constraints: List[cp.Constraint] = []
    add_triangle_socp_constraints(u_vars, n, constraints)
    add_all_berg_nikolaev_socp_constraints(u_vars, n, constraints)

    diff_terms = [u_vars[(i, j)] - float(U_target[i, j]) for i, j in combinations(range(n), 2)]
    obj = cp.Minimize(cp.sum_squares(cp.hstack(diff_terms)))
    prob = cp.Problem(obj, constraints)
    prob.solve(solver=choose_conic_solver())

    U_opt = np.zeros((n, n), dtype=float)
    for (i, j), var in u_vars.items():
        val = max(0.0, float(var.value))
        U_opt[i, j] = val
        U_opt[j, i] = val
    D_opt = np.sqrt(U_opt)
    frob = float(np.linalg.norm(D_opt - D, ord="fro"))
    return D_opt, frob


def project_onto_euclidean_sdp(D: np.ndarray) -> Tuple[np.ndarray, float]:
    """Project D^2 onto the exact Euclidean / Hilbert cone (Schoenberg Gram G >= 0) via CVXPY SDP."""
    D = np.asarray(D, dtype=float)
    n = D.shape[0]
    U_target = np.square(np.maximum(0.5 * (D + D.T), 0.0))
    G = cp.Variable((n, n), PSD=True)
    constraints = [cp.sum(G, axis=0) == 0]  # center coordinates at origin

    diff_terms = []
    for i, j in combinations(range(n), 2):
        u_ij = G[i, i] + G[j, j] - 2.0 * G[i, j]
        diff_terms.append(u_ij - float(U_target[i, j]))

    prob = cp.Problem(cp.Minimize(cp.sum_squares(cp.hstack(diff_terms))), constraints)
    prob.solve(solver=choose_conic_solver())

    G_val = np.asarray(G.value, dtype=float)
    U_opt = np.zeros((n, n), dtype=float)
    for i, j in combinations(range(n), 2):
        val = max(0.0, float(G_val[i, i] + G_val[j, j] - 2.0 * G_val[i, j]))
        U_opt[i, j] = val
        U_opt[j, i] = val
    D_opt = np.sqrt(U_opt)
    frob = float(np.linalg.norm(D_opt - D, ord="fro"))
    return D_opt, frob
