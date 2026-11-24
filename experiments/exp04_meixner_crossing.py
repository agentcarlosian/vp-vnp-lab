"""
Experiment 04: Meixner-Frobenius Crossing Identity (Proposition B.2 & B.3)
===========================================================================
Implements and symbolically/numerically verifies Proposition B.2 from
"VP != VNP Over Every Field":
  - Frobenius symbols (I, J) with |I| = |J| and energy sum(2i+1) + sum(2j+1)
  - Meixner polynomials B(r, n) and C(r, n) in y = X^2 and truncated orthogonality (B.1)
  - Block matrix M(X; s_a, s_b, s_c, s_d) and Psi = det(M)
  - Value at X = 1 gives crossing wires <|Sigma_1|>_{ac} <|Sigma_2|>_{bd}
  - Reflection symmetry X^Theta Psi(1/X; a,b,c,d) = Psi(X; a,d,c,b)
  - Exact simultaneous low-rank factorizations of Psi_N across BOTH cuts
    (a,d)|(b,c) and (a,b)|(c,d), compared against the theoretical bound (N+1)P(N).
"""

from itertools import combinations
from functools import lru_cache
import sympy as sp
import numpy as np

X = sp.Symbol("X")
Y = sp.Symbol("y")


@lru_cache(maxsize=None)
def meixner_B(r: int, n: int) -> sp.Expr:
    """Coefficient of t^n in (1 + t)^r / (1 + y*t)^(r + 1), as a polynomial in y."""
    expr = sp.Integer(0)
    for k in range(min(r, n) + 1):
        coeff = sp.binomial(r, k) * sp.binomial(r + n - k, n - k)
        expr += coeff * (-Y) ** (n - k)
    return sp.expand(expr)


@lru_cache(maxsize=None)
def meixner_C(r: int, n: int) -> sp.Expr:
    """Coefficient of t^n in (1 + y*t)^r / (1 + t)^(r + 1), as a polynomial in y."""
    expr = sp.Integer(0)
    for k in range(min(r, n) + 1):
        coeff = sp.binomial(r, k) * sp.binomial(r + n - k, n - k)
        expr += coeff * ((-1) ** (n - k)) * (Y ** k)
    return sp.expand(expr)


def verify_meixner_orthogonality(max_R: int = 5):
    """Verify (B.1): (1 - y) sum_{r<R} y^r B(r,i) B(r,j) == [i=j] y^i (mod y^R)."""
    for R in range(1, max_R + 1):
        for i in range(R):
            for j in range(R):
                lhs = sp.expand((1 - Y) * sum((Y ** r) * meixner_B(r, i) * meixner_B(r, j) for r in range(R)))
                rhs = (Y ** i) if i == j else sp.Integer(0)
                diff = sp.Poly(sp.expand(lhs - rhs), Y)
                for deg, coeff in diff.terms():
                    if deg[0] < R and coeff != 0:
                        raise AssertionError(f"Orthogonality failed for R={R}, i={i}, j={j}: diff={diff}")
    # Also verify C(r, n) = y^n B(r, n)|_{y -> 1/y}
    for r in range(max_R + 1):
        for n in range(max_R + 1):
            b_inv = sp.expand((Y ** n) * meixner_B(r, n).subs(Y, 1 / Y))
            assert sp.expand(b_inv - meixner_C(r, n)) == 0
    print(f"[PASS] Meixner orthogonality (B.1) and B/C reflection verified up to R={max_R}.")


def subsets_with_energy(size: int, max_energy: int, start: int = 0):
    """Yield sorted tuples of `size` distinct nonnegative integers with sum(2i+1) <= max_energy."""
    if size == 0:
        yield ()
        return
    # Minimum possible remaining energy starting at `start`
    min_rem = sum(2 * (start + t) + 1 for t in range(size))
    if min_rem > max_energy:
        return
    i = start
    while True:
        e_i = 2 * i + 1
        min_after = sum(2 * (i + 1 + t) + 1 for t in range(size - 1))
        if e_i + min_after > max_energy:
            break
        for rest in subsets_with_energy(size - 1, max_energy - e_i, i + 1):
            yield (i,) + rest
        i += 1


def symbols_of_size_and_energy(n: int, e: int):
    """All Frobenius symbols (I, J) with |I| = |J| = n and energy(I) + energy(J) = e."""
    res = []
    for I in subsets_with_energy(n, e):
        e_I = sum(2 * i + 1 for i in I)
        rem = e - e_I
        for J in subsets_with_energy(n, rem):
            if sum(2 * j + 1 for j in J) == rem:
                res.append((I, J))
    return res


def count_symbols_up_to_energy(E: int) -> int:
    """Exact P(E): number of Frobenius symbols of energy <= E."""
    total = 0
    # Minimum energy for size n is 2 * n^2
    n = 0
    while 2 * n * n <= E:
        for I in subsets_with_energy(n, E):
            e_I = sum(2 * i + 1 for i in I)
            for J in subsets_with_energy(n, E - e_I):
                total += 1
        n += 1
    return total


def build_M(sa, sb, sc, sd) -> sp.Matrix:
    """
    Build the square matrix M(X; sa, sb, sc, sd) from Section B.3 (p. 23).
    Rows indexed by I_a, I_d, I_c, I_b; columns by J_a, J_d, J_c, J_b.
    """
    Ia, Ja = sa
    Ib, Jb = sb
    Ic, Jc = sc
    Id, Jd = sd

    row_spec = [("a", i) for i in Ia] + [("d", i) for i in Id] + [("c", i) for i in Ic] + [("b", i) for i in Ib]
    col_spec = [("a", j) for j in Ja] + [("d", j) for j in Jd] + [("c", j) for j in Jc] + [("b", j) for j in Jb]

    y = X ** 2

    def B_X(r, n):
        return meixner_B(r, n).subs(Y, y)

    def C_X(r, n):
        return meixner_C(r, n).subs(Y, y)

    def entry(rp, i, cp, j):
        if rp == cp:
            return sp.Integer(0)
        if rp == "a" and cp == "d":
            return C_X(i, j)
        if rp == "a" and cp == "c":
            return X ** (2 * i + 1) if i == j else sp.Integer(0)
        if rp == "a" and cp == "b":
            return (y - 1) * (X ** (2 * i + 1)) * B_X(i, j)
        if rp == "d" and cp == "a":
            return -C_X(j, i)
        if rp == "d" and cp == "c":
            return (X ** (2 * j + 1)) * B_X(j, i)
        if rp == "d" and cp == "b":
            return -(X ** (2 * i + 1)) if i == j else sp.Integer(0)
        if rp == "c" and cp == "a":
            return -(X ** (2 * i + 1)) if i == j else sp.Integer(0)
        if rp == "c" and cp == "d":
            return -(X ** (2 * i + 1)) * B_X(i, j)
        if rp == "c" and cp == "b":
            return -(y - 1) * C_X(i, j)
        if rp == "b" and cp == "a":
            return -(y - 1) * (X ** (2 * j + 1)) * B_X(j, i)
        if rp == "b" and cp == "d":
            return X ** (2 * i + 1) if i == j else sp.Integer(0)
        if rp == "b" and cp == "c":
            return (y - 1) * C_X(j, i)
        raise ValueError((rp, cp))

    M = sp.Matrix(len(row_spec), len(col_spec), lambda r, c: entry(row_spec[r][0], row_spec[r][1], col_spec[c][0], col_spec[c][1]))
    return M


def run_crossing_experiment(n1: int, e1: int, n2: int, e2: int):
    Sigma1 = symbols_of_size_and_energy(n1, e1)
    Sigma2 = symbols_of_size_and_energy(n2, e2)
    Theta = 2 * (e1 + e2)
    d1, d2 = len(Sigma1), len(Sigma2)
    print(f"\n=== Crossing Identity Test: (n1={n1}, e1={e1}, |Sigma1|={d1}), (n2={n2}, e2={e2}, |Sigma2|={d2}), Theta={Theta} ===")
    print(f"  Sigma1 = {Sigma1}")
    print(f"  Sigma2 = {Sigma2}")

    # Store Psi_N[a, b, c, d] where c and d have swapped (I, J) as in B.3 so X=1 gives delta_{a,c} delta_{b,d}
    # First compute exact polynomials Psi(X; sa, sb, sc, sd) for raw symbols
    Psi_polys = {}
    for ia, sa in enumerate(Sigma1):
        for ib, sb in enumerate(Sigma2):
            for ic, sc_raw in enumerate(Sigma1):
                for id_, sd_raw in enumerate(Sigma2):
                    # Swap I and J at c and d as specified in Section B.3 ("The value at X = 1")
                    sc = (sc_raw[1], sc_raw[0])
                    sd = (sd_raw[1], sd_raw[0])
                    M = build_M(sa, sb, sc, sd)
                    p = sp.Poly(sp.expand(M.det()), X)
                    Psi_polys[(ia, ib, ic, id_)] = p

    # Check degree <= Theta and X = 1 value
    sign_eps = None
    max_deg = 0
    for (ia, ib, ic, id_), p in Psi_polys.items():
        if p.as_expr() != 0:
            max_deg = max(max_deg, p.degree())
        val1 = int(p.eval(1))
        if ia == ic and ib == id_:
            assert abs(val1) == 1, f"Expected +-1 at diagonal {(ia,ib,ic,id_)}, got {val1}"
            if sign_eps is None:
                sign_eps = val1
            else:
                assert val1 == sign_eps, f"Inconsistent sign: {val1} vs {sign_eps}"
        else:
            assert val1 == 0, f"Expected 0 off-diagonal {(ia,ib,ic,id_)}, got {val1}"
    assert max_deg <= Theta
    print(f"[PASS] Value at X=1 equals eps * <|Sigma1|>_{{ac}} <|Sigma2|>_{{bd}} with eps={sign_eps}, max_deg={max_deg} <= Theta={Theta}.")

    # Check reflection symmetry on raw symbols (before swapping c and d):
    # X^Theta * Psi(1/X; sa, sb, sc, sd) == Psi(X; sa, sd, sc, sb)
    # Note: for swapped index convention: swapping (sb, sd_swapped) -> check directly on a few tuples
    for ia, sa in enumerate(Sigma1):
        for ib, sb in enumerate(Sigma2):
            for ic, sc in enumerate(Sigma1):
                for id_, sd in enumerate(Sigma2):
                    # Use raw M for reflection test
                    p1 = sp.expand(build_M(sa, sb, sc, sd).det())
                    p2 = sp.expand(build_M(sa, sd, sc, sb).det())
                    refl = sp.expand((X ** Theta) * p1.subs(X, 1 / X))
                    assert sp.expand(refl - p2) == 0, f"Reflection failed at {(ia,ib,ic,id_)}"
    print(f"[PASS] Exact reflection symmetry X^Theta Psi(1/X; a,b,c,d) == Psi(X; a,d,c,b) verified on all {d1*d2*d1*d2} entries.")

    # Build tensors Psi_N (multiplied by sign_eps) and compute EXACT matrix ranks across BOTH cuts!
    Psi_N = np.zeros((Theta + 1, d1, d2, d1, d2), dtype=np.int64)
    for (ia, ib, ic, id_), p in Psi_polys.items():
        for N in range(Theta + 1):
            Psi_N[N, ia, ib, ic, id_] = sign_eps * int(p.nth(N))

    # Verify sum_N Psi_N == delta_{a,c} delta_{b,d}
    total = Psi_N.sum(axis=0)
    expected = np.einsum("ac,bd->abcd", np.eye(d1, dtype=np.int64), np.eye(d2, dtype=np.int64))
    assert np.array_equal(total, expected)
    print(f"[PASS] sum_{{N=0}}^{Theta} Psi_N == <|Sigma1|>_{{ac}} <|Sigma2|>_{{bd}} (exact integer tensor identity).")

    # Compare ranks across cut1 = (a,d)|(b,c) and cut2 = (a,b)|(c,d)
    # Full crossing tensor has rank d1 * d2 across BOTH cuts!
    print(f"\n  Full crossing tensor rank across BOTH cuts = {d1 * d2}")
    print(f"  {'N':>3} | {'rk(ad|bc)':>9} | {'bound (N+1)P(N)':>15} | {'rk(ab|cd)':>9} | {'bound (N\'+1)P(N\')':>17} | {'nonzero entries':>15}")
    print("  " + "-" * 80)
    nonzero_levels = 0
    for N in range(Theta + 1):
        T = Psi_N[N]
        nnz = int(np.count_nonzero(T))
        if nnz == 0:
            continue
        nonzero_levels += 1
        # Cut (a,d) | (b,c): reshape (d1*d2, d2*d1)
        M_ad_bc = T.transpose(0, 3, 1, 2).reshape(d1 * d2, d2 * d1)
        rk_ad_bc = int(sp.Matrix(M_ad_bc.tolist()).rank())
        # Cut (a,b) | (c,d): reshape (d1*d2, d1*d2)
        M_ab_cd = T.reshape(d1 * d2, d1 * d2)
        rk_ab_cd = int(sp.Matrix(M_ab_cd.tolist()).rank())

        Np = Theta - N
        b1 = (N + 1) * count_symbols_up_to_energy(N)
        b2 = (Np + 1) * count_symbols_up_to_energy(Np)
        assert rk_ad_bc <= b1, f"Bound (b) violated at N={N}: {rk_ad_bc} > {b1}"
        assert rk_ab_cd <= b2, f"Bound (c) violated at N={N}: {rk_ab_cd} > {b2}"
        print(f"  {N:>3} | {rk_ad_bc:>9} | {b1:>15} | {rk_ab_cd:>9} | {b2:>17} | {nnz:>15}")

    print(f"[PASS] All {nonzero_levels} nonzero Psi_N satisfy BOTH exact integer rank bounds simultaneously!")
    return Psi_N


if __name__ == "__main__":
    verify_meixner_orthogonality(max_R=6)
    # Test 1: n1=1, e1=6 (symbols: ({0},{2}), ({1},{1}), ({2},{0}) -> |Sigma1|=3),
    #         n2=1, e2=4 (symbols: ({0},{1}), ({1},{0}) -> |Sigma2|=2). Full rank = 6!
    run_crossing_experiment(n1=1, e1=6, n2=1, e2=4)
    # Test 2: n1=1, e1=6 (|Sigma1|=3), n2=1, e2=6 (|Sigma2|=3). Full rank = 9!
    run_crossing_experiment(n1=1, e1=6, n2=1, e2=6)
    # Test 3: n1=1, e1=8 (|Sigma1|=4), n2=1, e2=6 (|Sigma2|=3). Full rank = 12!
    run_crossing_experiment(n1=1, e1=8, n2=1, e2=6)
