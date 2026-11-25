"""Exact Rational Farkas/Dual Certificate Extractor & Lean 4 Proof Exporter for CAT(0)/Enflo Bounds."""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from itertools import combinations
from math import gcd
from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy.optimize import linprog

from .models import QuantumNetwork


def _canon(u: int, v: int) -> Tuple[int, int]:
    return (u, v) if u < v else (v, u)


def _lcm(a: int, b: int) -> int:
    return abs(a * b) // gcd(a, b) if a and b else max(abs(a), abs(b), 1)


@dataclass
class DualConstraintTerm:
    kind: str                          # "triangle_sq" | "enflo_4cycle"
    vertices: Tuple[int, ...]          # (i, j, k) or (a, b, c, d)
    weight: Fraction                   # strictly positive exact rational multiplier
    description: str


@dataclass
class RationalEnfloCertificate:
    network_name: str
    num_parties: int
    exact_rho_enflo: Fraction
    float_rho_enflo: float
    verified_exact: bool
    active_terms: List[DualConstraintTerm] = field(default_factory=list)
    edge_slacks: Dict[Tuple[int, int], Fraction] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, object]:
        return {
            "network_name": self.network_name,
            "num_parties": self.num_parties,
            "exact_rho_enflo": f"{self.exact_rho_enflo.numerator}/{self.exact_rho_enflo.denominator}",
            "float_rho_enflo": round(self.float_rho_enflo, 8),
            "verified_exact": self.verified_exact,
            "active_term_count": len(self.active_terms),
            "active_terms": [
                {
                    "kind": t.kind,
                    "vertices": list(t.vertices),
                    "weight": f"{t.weight.numerator}/{t.weight.denominator}",
                    "description": t.description,
                }
                for t in self.active_terms
            ],
        }


def extract_enflo_dual_certificate(
    net: QuantumNetwork,
    *,
    max_denom: int = 10_000,
) -> RationalEnfloCertificate:
    """Extract and exact-Fraction-verify a rational Farkas dual proof for the Enflo/CAT(0) quadratic bound.

    Primal over squared distances u_e >= 0:
      maximize    c^T u = sum_{f in T} t_f u_f
      subject to  s^T u <= 1
                  A_cone u <= 0   (all squared-triangle u_ik - 2 u_ij - 2 u_jk <= 0
                                   and Enflo 4-cycle u_ac + u_bd - u_ab - u_bc - u_cd - u_da <= 0)

    LP Dual (exact Farkas certificate):
      minimize    rho >= 0
      subject to  rho * s + A_cone^T y >= c,   y >= 0.
    """
    if net.source_ghz:
        raise ValueError("Exact polyhedral Enflo dual certificate currently requires pairwise EPR sources.")

    n = net.num_parties
    edges = list(combinations(range(n), 2))
    edge_idx = {e: idx for idx, e in enumerate(edges)}
    m_edges = len(edges)

    s_vec = np.zeros(m_edges, dtype=float)
    c_vec = np.zeros(m_edges, dtype=float)
    s_frac = [Fraction(0) for _ in range(m_edges)]
    c_frac = [Fraction(0) for _ in range(m_edges)]

    for e, w in net.source_eprs.items():
        idx = edge_idx[_canon(*e)]
        s_vec[idx] = float(w)
        s_frac[idx] = Fraction(w)
    for f, w in net.target_eprs.items():
        idx = edge_idx[_canon(*f)]
        c_vec[idx] = float(w)
        c_frac[idx] = Fraction(w)

    # Enumerate cone inequalities row_k * u <= 0
    rows_frac: List[Dict[int, int]] = []
    meta: List[Tuple[str, Tuple[int, ...], str]] = []

    # 1. Squared-triangle inequalities: u_ik - 2 u_ij - 2 u_jk <= 0 (valid on every metric space since (d_ij+d_jk)^2 <= 2(d_ij^2+d_jk^2))
    for i, j, k in combinations(range(n), 3):
        for a, b, c in ((i, k, j), (i, j, k), (j, k, i)):
            # u_{a,b} - 2 u_{a,c} - 2 u_{c,b} <= 0
            rows_frac.append({
                edge_idx[_canon(a, b)]: 1,
                edge_idx[_canon(a, c)]: -2,
                edge_idx[_canon(c, b)]: -2,
            })
            meta.append(("triangle_sq", (a, c, b), f"u({a},{b}) <= 2*u({a},{c}) + 2*u({c},{b})"))

    # 2. Enflo roundness-2 4-cycle inequalities (direct consequence of Berg-Nikolaev + AM-GM in every CAT(0) space):
    #    u_ac + u_bd - u_ab - u_bc - u_cd - u_da <= 0
    for a, b, c, d in combinations(range(n), 4):
        for v0, v1, v2, v3 in ((a, b, c, d), (a, c, b, d), (a, b, d, c)):
            rows_frac.append({
                edge_idx[_canon(v0, v2)]: 1,
                edge_idx[_canon(v1, v3)]: 1,
                edge_idx[_canon(v0, v1)]: -1,
                edge_idx[_canon(v1, v2)]: -1,
                edge_idx[_canon(v2, v3)]: -1,
                edge_idx[_canon(v3, v0)]: -1,
            })
            meta.append((
                "enflo_4cycle",
                (v0, v1, v2, v3),
                f"u({v0},{v2}) + u({v1},{v3}) <= u({v0},{v1}) + u({v1},{v2}) + u({v2},{v3}) + u({v3},{v0})",
            ))

    n_rows = len(rows_frac)
    # Solve dual LP directly via HiGHS:
    # Variables x = [rho, y_0, ..., y_{n_rows-1}] >= 0
    # Minimize rho + 1e-9 * sum(y)  (tiny L1 regularization yields sparse, clean rational certificates!)
    obj = np.zeros(1 + n_rows, dtype=float)
    obj[0] = 1.0
    obj[1:] = 1e-9

    # Constraint: -(rho * s + A^T y) <= -c
    A_ub = np.zeros((m_edges, 1 + n_rows), dtype=float)
    A_ub[:, 0] = -s_vec
    for r_idx, row in enumerate(rows_frac):
        for e_i, coeff in row.items():
            A_ub[e_i, 1 + r_idx] = -float(coeff)
    b_ub = -c_vec

    res = linprog(obj, A_ub=A_ub, b_ub=b_ub, bounds=(0.0, None), method="highs")
    if not res.success or res.x is None:
        raise RuntimeError(f"Dual certificate LP failed on {net.name}: {res.message}")

    rho_flt = float(res.x[0])
    y_flt = res.x[1:]

    # Rationalize active multipliers & compute exact required rho_frac so domination holds with ZERO error!
    y_frac: Dict[int, Fraction] = {}
    for r_idx, val in enumerate(y_flt):
        if val > 1e-7:
            q = Fraction(float(val)).limit_denominator(max_denom)
            if q > 0:
                y_frac[r_idx] = q

    # From c_e <= rho * s_e + (A^T y)_e for all edges e:
    #   - If s_e == 0, we need (A^T y)_e >= c_e
    #   - If s_e > 0,  rho >= (c_e - (A^T y)_e) / s_e
    aty = [Fraction(0) for _ in range(m_edges)]
    for r_idx, q in y_frac.items():
        for e_i, coeff in rows_frac[r_idx].items():
            aty[e_i] += q * coeff

    rho_req = Fraction(0)
    exact_ok = True
    for e_i in range(m_edges):
        needed = c_frac[e_i] - aty[e_i]
        if s_frac[e_i] == 0:
            if needed > 0:
                exact_ok = False
        else:
            cand = needed / s_frac[e_i]
            if cand > rho_req:
                rho_req = cand

    slacks: Dict[Tuple[int, int], Fraction] = {}
    for e_i, e in enumerate(edges):
        sl = rho_req * s_frac[e_i] + aty[e_i] - c_frac[e_i]
        slacks[e] = sl
        if sl < 0:
            exact_ok = False

    active_terms = [
        DualConstraintTerm(
            kind=meta[r_idx][0],
            vertices=meta[r_idx][1],
            weight=q,
            description=meta[r_idx][2],
        )
        for r_idx, q in sorted(y_frac.items())
    ]

    return RationalEnfloCertificate(
        network_name=net.name,
        num_parties=n,
        exact_rho_enflo=rho_req,
        float_rho_enflo=float(rho_req),
        verified_exact=exact_ok,
        active_terms=active_terms,
        edge_slacks=slacks,
    )


def export_lean4_enflo_certificate(net: QuantumNetwork, cert: RationalEnfloCertificate) -> str:
    """Render a standalone, zero-sorry, zero-Mathlib Lean 4 proof module from a verified rational certificate."""
    if not cert.verified_exact:
        raise ValueError(f"Cannot export unverified certificate for {net.name}")

    # Clear denominators of the exact coefficients appearing in the theorem.
    target = {e: Fraction(w) for e, w in net.target_eprs.items()}
    source = {e: Fraction(w) * cert.exact_rho_enflo for e, w in net.source_eprs.items()}
    scale = 1
    for coeff in (*target.values(), *source.values()):
        scale = _lcm(scale, coeff.denominator)

    def u_call(i: int, j: int) -> str:
        a, b = _canon(i, j)
        return f"u {a} {b}"

    tgt_parts = []
    for (i, j), w in sorted(target.items()):
        coeff = int(w * scale)
        tgt_parts.append(f"{coeff} * {u_call(i, j)}" if coeff != 1 else u_call(i, j))
    tgt_expr = " + ".join(tgt_parts) if tgt_parts else "0"

    src_parts = []
    for (i, j), w in sorted(source.items()):
        coeff = int(w * scale)
        if coeff != 0:
            src_parts.append(f"{coeff} * {u_call(i, j)}" if coeff != 1 else u_call(i, j))
    src_expr = " + ".join(src_parts) if src_parts else "0"

    hyps = ["(u : Nat → Nat → Int)"]
    # Non-negativity hypotheses on all edge variables
    for i, j in combinations(range(net.num_parties), 2):
        hyps.append(f"(hnn_{i}_{j} : 0 ≤ {u_call(i, j)})")
    for idx, t in enumerate(cert.active_terms):
        if t.kind == "triangle_sq":
            a, c, b = t.vertices
            hyps.append(f"(htri_{idx} : {u_call(a, b)} ≤ 2 * {u_call(a, c)} + 2 * {u_call(c, b)})")
        else:
            v0, v1, v2, v3 = t.vertices
            hyps.append(
                f"(henf_{idx} : {u_call(v0, v2)} + {u_call(v1, v3)} ≤ "
                f"{u_call(v0, v1)} + {u_call(v1, v2)} + {u_call(v2, v3)} + {u_call(v3, v0)})"
            )

    safe_name = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in net.name).lower()
    binders_str = "\n    ".join(hyps)
    return (
        f"/-!\n"
        f"  Auto-generated by `qcat0 certify` for quantum network `{net.name}` (n={net.num_parties}).\n"
        f"  Exact rational Enflo/CAT(0) bound: rho = {cert.exact_rho_enflo} ({len(cert.active_terms)} active dual constraints).\n"
        f"  Zero `sorry`, zero custom axioms, zero Mathlib dependency.\n"
        f"-/\n\n"
        f"namespace QCat0Cert\n\n"
        f"theorem {safe_name}_cat0_enflo_bound\n"
        f"    {binders_str} :\n"
        f"    {tgt_expr} ≤ {src_expr} := by\n"
        f"  omega\n\n"
        f"end QCat0Cert\n"
    )
