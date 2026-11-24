"""Mathematical & CVXPY verification tests for quantum-cat0-checker."""

from __future__ import annotations

import math
import pathlib
import sys

import numpy as np
import pytest

PKG_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

from quantum_cat0.cat0_cone import audit_metric_cat0, project_onto_cat0_socp, project_onto_euclidean_sdp
from quantum_cat0.models import QuantumNetwork, get_topology
from quantum_cat0.solvers import check_slocc_feasibility, solve_covering_capacity_hierarchy


def test_audit_metric_distinguishes_euclidean_cat0_and_l1():
    # 1. Euclidean unit square: CAT(0) AND Euclidean
    D_sq = np.array([
        [0, 1, math.sqrt(2), 1],
        [1, 0, 1, math.sqrt(2)],
        [math.sqrt(2), 1, 0, 1],
        [1, math.sqrt(2), 1, 0],
    ], dtype=float)
    r_sq = audit_metric_cat0(D_sq)
    assert r_sq.is_valid_metric and r_sq.is_cat0_4pt and r_sq.is_euclidean_embeddable

    # 2. L1 cycle C_4 (sides=1, diagonals=2): valid metric, NOT CAT(0), NOT Euclidean
    D_l1 = np.array([
        [0, 1, 2, 1],
        [1, 0, 1, 2],
        [2, 1, 0, 1],
        [1, 2, 1, 0],
    ], dtype=float)
    r_l1 = audit_metric_cat0(D_l1, compute_projections=True)
    assert r_l1.is_valid_metric
    assert not r_l1.is_cat0_4pt
    assert r_l1.max_berg_nikolaev_violation > 1.5
    assert r_l1.cat0_projection_frobenius_dist is not None and r_l1.cat0_projection_frobenius_dist > 0.3

    # 3. 4-leaf star tree (center + 3 leaves: Wait — K_{1,3} is 4 points, tree metric is CAT(0) but NOT Euclidean!)
    # Check 4-point star (0=center, 1,2,3=leaves at dist 1 from center, dist 2 between leaves):
    # Gram eigenvalues of K_{1,3}: centered distances have negative eigenvalue -> NOT Euclidean, YES CAT(0)!
    D_star = np.array([
        [0, 1, 1, 1],
        [1, 0, 2, 2],
        [1, 2, 0, 2],
        [1, 2, 2, 0],
    ], dtype=float)
    r_star = audit_metric_cat0(D_star)
    assert r_star.is_valid_metric
    assert r_star.is_cat0_4pt          # Trees are CAT(0)!
    assert not r_star.is_euclidean_embeddable  # K_{1,3} does NOT embed isometrically in any R^d!


def test_socp_and_sdp_projections_produce_valid_metrics():
    D_l1 = np.array([[0, 1, 2, 1], [1, 0, 1, 2], [2, 1, 0, 1], [1, 2, 1, 0]], dtype=float)
    D_cat0, d1 = project_onto_cat0_socp(D_l1)
    D_euc, d2 = project_onto_euclidean_sdp(D_l1)
    assert audit_metric_cat0(D_cat0, tol=1e-4).is_cat0_4pt
    assert audit_metric_cat0(D_euc, tol=1e-4).is_euclidean_embeddable
    assert d1 <= d2 + 1e-4  # Euclidean cone is a subset of CAT(0) cone!


def test_c4_crossing_exact_sqrt2_compression():
    net = get_topology("C4_crossing")
    res = solve_covering_capacity_hierarchy(net)
    assert math.isclose(res.rho_metric, 2.0, rel_tol=1e-3)
    assert math.isclose(res.rho_cat0, 1.0, rel_tol=1e-3)
    assert math.isclose(res.rho_euclidean, 1.0, rel_tol=1e-3)
    assert math.isclose(res.ebit_budget_metric, 4.0, rel_tol=1e-3)
    assert math.isclose(res.ebit_budget_cat0, 2.0 * math.sqrt(2.0), rel_tol=1e-3)
    assert math.isclose(res.cat0_compression_ratio, math.sqrt(2.0), rel_tol=1e-3)
    assert res.witness_cat0_max_bn_violation < 1e-4


def test_k3_triangle_zero_cat0_gap():
    net = get_topology("K3_triangle")
    res = solve_covering_capacity_hierarchy(net)
    assert math.isclose(res.rho_metric, res.rho_cat0, rel_tol=1e-3)
    assert math.isclose(res.cat0_compression_ratio, 1.0, rel_tol=1e-3)


def test_hypercube_q3_exact_sqrt3_enflo_compression():
    net = get_topology("hypercube_Q3")
    res = solve_covering_capacity_hierarchy(net)
    # In L1 cube: sides=1, body diagonals=3 -> rho_M = 4*9 / 12 = 3.0
    # In CAT(0) / Euclidean cube: sides=1, body diagonals=sqrt(3) -> rho_CAT0 = 4*3 / 12 = 1.0 -> sqrt(3)x gain!
    assert math.isclose(res.rho_metric, 3.0, rel_tol=1e-3)
    assert math.isclose(res.rho_cat0, 1.0, rel_tol=2e-3)
    assert math.isclose(res.cat0_compression_ratio, math.sqrt(3.0), rel_tol=2e-3)


def test_slocc_single_restriction_cut_vs_l2_cover_separation():
    net = get_topology("C4_infeasible_single")
    feas = check_slocc_feasibility(net)
    # 4 sides of 0.75 ebits = 3.0 total ebits >= 2*sqrt(2) = 2.8284 (L2 cover achievable!),
    # yet bipartition cut has 1.5 < 2.0 (single SLOCC restriction FORBIDDEN!)
    assert feas.verdict == "FORBIDDEN_BY_CUT"
    assert math.isclose(feas.min_cut_ratio, 0.75, rel_tol=1e-4)
    assert feas.covering_feasible_with_l2_cover is True


def test_cutting_plane_matches_full_socp_on_butterfly6():
    net = get_topology("butterfly_6")
    full = solve_covering_capacity_hierarchy(net, cutting_plane_threshold_n=10)
    lazy = solve_covering_capacity_hierarchy(net, cutting_plane_threshold_n=3)
    assert math.isclose(full.rho_cat0, lazy.rho_cat0, rel_tol=1e-3)
    assert lazy.witness_cat0_max_bn_violation < 1e-4


def test_k23_strict_three_way_cone_separation():
    """K_{2,3} strictly separates Euclidean (1.5) < CAT(0) (2.0) < Metric (8/3)."""
    net = get_topology("K23_bipartite")
    res = solve_covering_capacity_hierarchy(net)
    assert math.isclose(res.rho_euclidean, 1.5, rel_tol=1e-3)
    assert math.isclose(res.rho_cat0, 2.0, rel_tol=1e-3)
    assert math.isclose(res.rho_metric, 8.0 / 3.0, rel_tol=1e-3)
    assert res.rho_euclidean < res.rho_cat0 < res.rho_metric
