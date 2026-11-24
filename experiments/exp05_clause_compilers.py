"""
Experiment 05: Exact Compilers for Grid Sums / Weighted Clause Sums -> PERM & HC
=================================================================================
Implements:
  1. Proposition E.1: Arbitrary grid sum -> 3|I| x 3|I| permanent matrix (over Z[1/2])
  2. Corollary E.2:   Arbitrary weighted clause sum -> 3q x 3q permanent matrix
  3. Proposition M.2: Arbitrary grid sum -> <= 39|I| x 39|I| directed Hamiltonian cycle
                      adjacency matrix (division-free, valid over EVERY commutative ring including F2!)

Verifies exact numerical & symbolic equality against:
  - Direct brute-force evaluation of the grid/clause sum
  - Ryser's formula for PERM_M
  - Held-Karp exact DP for HC_M (over Z and over F2!)

Benchmarks tested:
  - f_{3,1} (the 2x2 matrix multiplication trilinear form from Section E.2)
  - Weighted #SAT / clause-sum instances with arbitrary ring weights
  - General non-boolean 2x2 matrix grid sums over Z and F2
"""

from fractions import Fraction
import numpy as np


# ---------------------------------------------------------------------------
# Exact Permanent (Ryser's formula) and Hamiltonian Cycle (Held-Karp DP)
# ---------------------------------------------------------------------------

def permanent_ryser(M):
    """Exact permanent of an n x n matrix M using Ryser's formula (works over Fraction/int/float)."""
    n = len(M)
    if n == 0:
        return Fraction(1)
    # Gray-code Ryser for speed: O(n * 2^n)
    row_sums = [Fraction(0)] * n
    total = Fraction(0)
    prev_gray = 0
    sign = 1  # (-1)^|S|
    for step in range(1, 1 << n):
        gray = step ^ (step >> 1)
        diff = gray ^ prev_gray
        col = diff.bit_length() - 1
        if gray & diff:
            for i in range(n):
                row_sums[i] += M[i][col]
            sign = -sign
        else:
            for i in range(n):
                row_sums[i] -= M[i][col]
            sign = -sign
        prod = Fraction(1)
        for rs in row_sums:
            prod *= rs
            if prod == 0:
                break
        if sign == 1:
            total += prod
        else:
            total -= prod
        prev_gray = gray
    if n % 2 == 1:
        total = -total
    return total


def hc_exact_dp(adj, mod=None):
    """
    100% general exact Hamiltonian cycle polynomial HC_n(adj) solver for any directed weighted graph.
    Uses exact constraint propagation (forced unique in/out edges + premature-subcycle pruning)
    combined with MRV branching (branch on vertex with fewest valid outgoing edges).
    Zero knowledge of Prop M.2 structure; exact on every directed graph and millisecond-fast on sparse graphs!
    """
    n = len(adj)
    if n == 0:
        return 1
    if n == 1:
        val = adj[0][0]
        return val % mod if mod else val

    out_adj = [[] for _ in range(n)]
    in_adj = [[] for _ in range(n)]
    for u in range(n):
        for v in range(n):
            w = adj[u][v]
            if w != 0:
                if u == v:
                    continue  # self-loops can't be in an n-cycle for n >= 2
                out_adj[u].append((v, w))
                in_adj[v].append((u, w))

    # Quick degree check
    for u in range(n):
        if not out_adj[u] or not in_adj[u]:
            return 0

    def solve(out_ch, in_ch, head, tail, num_edges, weight):
        # Propagate forced unique out-edges and in-edges until fixpoint
        changed = True
        while changed:
            changed = False
            if num_edges == n:
                return weight
            for u in range(n):
                if out_ch[u] == -1:
                    valid = None
                    cnt = 0
                    for v, w in out_adj[u]:
                        if in_ch[v] != -1:
                            continue
                        if head[u] == v and num_edges < n - 1:
                            continue
                        cnt += 1
                        valid = (v, w)
                        if cnt > 1:
                            break
                    if cnt == 0:
                        return 0
                    if cnt == 1:
                        v, w = valid
                        out_ch[u] = v
                        in_ch[v] = u
                        hu = head[u]
                        tv = tail[v]
                        head[tv] = hu
                        tail[hu] = tv
                        num_edges += 1
                        weight = (weight * w) % mod if mod else (weight * w)
                        if weight == 0:
                            return 0
                        changed = True
            for v in range(n):
                if in_ch[v] == -1:
                    valid = None
                    cnt = 0
                    for u, w in in_adj[v]:
                        if out_ch[u] != -1:
                            continue
                        if head[u] == v and num_edges < n - 1:
                            continue
                        cnt += 1
                        valid = (u, w)
                        if cnt > 1:
                            break
                    if cnt == 0:
                        return 0
                    if cnt == 1:
                        u, w = valid
                        out_ch[u] = v
                        in_ch[v] = u
                        hu = head[u]
                        tv = tail[v]
                        head[tv] = hu
                        tail[hu] = tv
                        num_edges += 1
                        weight = (weight * w) % mod if mod else (weight * w)
                        if weight == 0:
                            return 0
                        changed = True

        if num_edges == n:
            return weight

        # Branch on unchosen vertex with minimum number of valid out-edges (MRV)
        best_u = -1
        best_opts = None
        for u in range(n):
            if out_ch[u] == -1:
                opts = []
                for v, w in out_adj[u]:
                    if in_ch[v] != -1:
                        continue
                    if head[u] == v and num_edges < n - 1:
                        continue
                    opts.append((v, w))
                if not opts:
                    return 0
                if best_opts is None or len(opts) < len(best_opts):
                    best_u = u
                    best_opts = opts
                    if len(best_opts) == 2:
                        break

        total = 0
        for v, w in best_opts:
            nw = (weight * w) % mod if mod else (weight * w)
            if nw == 0:
                continue
            oc = out_ch.copy()
            ic = in_ch.copy()
            hd = head.copy()
            tl = tail.copy()
            oc[best_u] = v
            ic[v] = best_u
            hu = hd[best_u]
            tv = tl[v]
            hd[tv] = hu
            tl[hu] = tv
            res = solve(oc, ic, hd, tl, num_edges + 1, nw)
            total = (total + res) % mod if mod else (total + res)
        return total

    return solve([-1] * n, [-1] * n, list(range(n)), list(range(n)), 0, 1)


# ---------------------------------------------------------------------------
# Grid sum evaluation (ground truth)
# ---------------------------------------------------------------------------

def eval_grid_sum(v_map, w_map, W_mats, mod=None):
    """
    Compute sum_{x in {0,1}^V} sum_{r in {0,1}^K} prod_{n in I} W_n(x_{v(n)}, r_{w(n)}).
    v_map: list of length |I| with values in 0..|V|-1
    w_map: list of length |I| with values in 0..|K|-1
    W_mats: list of length |I| of 2x2 arrays W[x][r]
    """
    V = max(v_map) + 1
    K = max(w_map) + 1
    I = len(v_map)
    total = Fraction(0) if mod is None else 0
    for x_mask in range(1 << V):
        for r_mask in range(1 << K):
            prod = Fraction(1) if mod is None else 1
            for n in range(I):
                xv = (x_mask >> v_map[n]) & 1
                rw = (r_mask >> w_map[n]) & 1
                val = W_mats[n][xv][rw]
                prod = (prod * val) % mod if mod else (prod * val)
                if prod == 0:
                    break
            total = (total + prod) % mod if mod else (total + prod)
    return total


def eval_clause_sum(num_bits, clauses, mod=None):
    """
    clauses: list of (literals, weight) where literals is list of (bit_idx, expected_val in {0,1}).
    Computes sum_{x in {0,1}^V} prod_j (w_j if x satisfies clause j else 1).
    """
    total = Fraction(0) if mod is None else 0
    for x_mask in range(1 << num_bits):
        prod = Fraction(1) if mod is None else 1
        for lits, w in clauses:
            sat = all(((x_mask >> b) & 1) == val for b, val in lits)
            if sat:
                prod = (prod * w) % mod if mod else (prod * w)
        total = (total + prod) % mod if mod else (total + prod)
    return total


# ---------------------------------------------------------------------------
# Proposition E.1: Grid sum -> 3|I| x 3|I| Permanent matrix
# ---------------------------------------------------------------------------

def compile_grid_sum_to_perm(v_map, w_map, W_mats):
    """
    Construct the exact 3|I| x 3|I| matrix of Proposition E.1 (p. 32).
    """
    I = len(v_map)
    # Build cyclic permutations sigma (fibers of v) and rho (fibers of w)
    sigma = [0] * I
    rho = [0] * I

    v_fibers = {}
    for n, v in enumerate(v_map):
        v_fibers.setdefault(v, []).append(n)
    for fib in v_fibers.values():
        for idx in range(len(fib)):
            sigma[fib[idx]] = fib[(idx + 1) % len(fib)]

    w_fibers = {}
    for n, w in enumerate(w_map):
        w_fibers.setdefault(w, []).append(n)
    for fib in w_fibers.values():
        for idx in range(len(fib)):
            rho[fib[idx]] = fib[(idx + 1) % len(fib)]

    # Columns: A_n = 3*n, B_n = 3*n + 1, C_n = 3*n + 2
    size = 3 * I
    M = [[Fraction(0) for _ in range(size)] for _ in range(size)]
    half = Fraction(1, 2)

    for n in range(I):
        A_n, B_n, C_n = 3 * n, 3 * n + 1, 3 * n + 2
        A_sig = 3 * sigma[n]
        B_rho, C_rho = 3 * rho[n] + 1, 3 * rho[n] + 2

        # Row 1: 1/2 (A_n + B_n + A_{sigma n} - C_n)
        r1 = 3 * n
        M[r1][A_n] += half
        M[r1][B_n] += half
        M[r1][A_sig] += half
        M[r1][C_n] -= half

        # Row 2: A_n + B_n - A_{sigma n} + C_n
        r2 = 3 * n + 1
        M[r2][A_n] += 1
        M[r2][B_n] += 1
        M[r2][A_sig] -= 1
        M[r2][C_n] += 1

        # Row 3: W_n(1,1) C_n + W_n(0,1) B_n + W_{rho n}(1,0) C_{rho n} + W_{rho n}(0,0) B_{rho n}
        r3 = 3 * n + 2
        rn = rho[n]
        M[r3][C_n] += Fraction(W_mats[n][1][1])
        M[r3][B_n] += Fraction(W_mats[n][0][1])
        M[r3][C_rho] += Fraction(W_mats[rn][1][0])
        M[r3][B_rho] += Fraction(W_mats[rn][0][0])

    return M


def clause_sum_to_grid_sum(num_bits, clauses):
    """
    Corollary E.2 conversion: clause sum with q literals -> grid sum with |I| = q.
    Ensures every bit occurs in at least one literal by adding a weight-1 dummy clause if needed.
    """
    used = set()
    for lits, _ in clauses:
        for b, _ in lits:
            used.add(b)
    all_clauses = list(clauses)
    for b in range(num_bits):
        if b not in used:
            all_clauses.append(([(b, 1)], Fraction(1)))

    v_map = []
    w_map = []
    W_mats = []
    for c_idx, (lits, w) in enumerate(all_clauses):
        for l_idx, (bit, target) in enumerate(lits):
            v_map.append(bit)
            w_map.append(c_idx)
            # r = 0 -> contributes 1
            # r = 1 -> contributes (w - 1) * indicator on first literal, indicator on others
            ind0 = 1 if target == 0 else 0
            ind1 = 1 if target == 1 else 0
            factor = (w - 1) if l_idx == 0 else Fraction(1)
            W_mats.append([
                [Fraction(1), factor * ind0],  # x = 0: r=0, r=1
                [Fraction(1), factor * ind1],  # x = 1: r=0, r=1
            ])
    return v_map, w_map, W_mats


# ---------------------------------------------------------------------------
# Proposition M.2: Grid sum -> <= 39|I| x 39|I| Directed Hamiltonian Cycle graph
# ---------------------------------------------------------------------------

def compile_grid_sum_to_hc(v_map, w_map, W_mats):
    """
    Construct the weighted directed graph of Proposition M.2 (p. 61).
    Zero divisions! Entries are only 0, 1, and single values W_n(x, r).
    Returns weighted adjacency matrix A (size <= 39|I|).
    """
    I = len(v_map)
    V = max(v_map) + 1
    K = max(w_map) + 1

    # Segments: each segment is a list of options.
    # Each option has: name, weight, list of (xor_id, direction) where direction in (+1: a->b->c, -1: c->b->a).
    segments = []
    option_xors = {}   # (seg_idx, opt_name) -> list of (xor_id, dir)
    option_weight = {} # (seg_idx, opt_name) -> weight

    def add_segment(opt_specs):
        s_idx = len(segments)
        names = []
        for name, wt in opt_specs:
            names.append(name)
            option_xors[(s_idx, name)] = []
            option_weight[(s_idx, name)] = wt
        segments.append(names)
        return s_idx

    xor_count = 0

    def add_xor(opt1, opt2):
        nonlocal xor_count
        xid = xor_count
        xor_count += 1
        option_xors[opt1].append((xid, +1))
        option_xors[opt2].append((xid, -1))

    # 1. Segments for V (x bits) and K (r bits)
    v_seg = [add_segment([("T", 1), ("F", 1)]) for _ in range(V)]
    k_seg = [add_segment([("T", 1), ("F", 1)]) for _ in range(K)]

    # 2. For each n in I, 7 segments and 10 XORs (p. 61)
    T_KEYS = [("TT", 1, 1), ("TF", 1, 0), ("FT", 0, 1), ("FF", 0, 0)]
    for n in range(I):
        # Selector segment: options s_t with weight W_n(x, r)
        sel = add_segment([(f"s_{t}", W_mats[n][xv][rw]) for t, xv, rw in T_KEYS])
        # 4 flag segments: y_t and ybar_t
        flags = {t: add_segment([(f"y_{t}", 1), (f"ybar_{t}", 1)]) for t, _, _ in T_KEYS}
        # x-check segment: xi_TT, xi_TF, xi_0
        xchk = add_segment([("xi_TT", 1), ("xi_TF", 1), ("xi_0", 1)])
        # r-check segment: rho_TT, rho_FT, rho_0
        rchk = add_segment([("rho_TT", 1), ("rho_FT", 1), ("rho_0", 1)])

        # 4 XORs joining ybar_t with s_t
        for t, _, _ in T_KEYS:
            add_xor((flags[t], f"ybar_{t}"), (sel, f"s_{t}"))
        # 2 XORs joining ybar_t with xi_t for t in {TT, TF}
        add_xor((flags["TT"], "ybar_TT"), (xchk, "xi_TT"))
        add_xor((flags["TF"], "ybar_TF"), (xchk, "xi_TF"))
        # 2 XORs joining ybar_t with rho_t for t in {TT, FT}
        add_xor((flags["TT"], "ybar_TT"), (rchk, "rho_TT"))
        add_xor((flags["FT"], "ybar_FT"), (rchk, "rho_FT"))
        # 1 XOR joining xi_0 with option T of v(n), and 1 joining rho_0 with option T of w(n)
        add_xor((xchk, "xi_0"), (v_seg[v_map[n]], "T"))
        add_xor((rchk, "rho_0"), (k_seg[w_map[n]], "T"))

    # Build vertices: S junctions + 3 * xor_count XOR vertices (a, b, c)
    S = len(segments)
    num_verts = S + 3 * xor_count
    assert num_verts <= 39 * I, f"Vertex count {num_verts} > 39*{I}"

    A = [[0 for _ in range(num_verts)] for _ in range(num_verts)]

    # Add bidirectional edges inside each XOR: a <-> b <-> c
    for xid in range(xor_count):
        a = S + 3 * xid
        b = a + 1
        c = a + 2
        A[a][b] = 1
        A[b][c] = 1
        A[c][b] = 1
        A[b][a] = 1

    # Connect each option from junction s to junction (s + 1) % S through its XORs
    for s_idx, names in enumerate(segments):
        u_start = s_idx
        u_end = (s_idx + 1) % S
        zero_xor_opts = 0
        for name in names:
            xlist = option_xors[(s_idx, name)]
            wt = option_weight[(s_idx, name)]
            if len(xlist) == 0:
                zero_xor_opts += 1
                assert zero_xor_opts <= 1, f"Parallel direct edge at segment {s_idx}"
                assert A[u_start][u_end] == 0
                A[u_start][u_end] = wt
            else:
                curr = u_start
                for idx, (xid, d) in enumerate(xlist):
                    a = S + 3 * xid
                    c = a + 2
                    entry_v = a if d == +1 else c
                    exit_v = c if d == +1 else a
                    edge_wt = wt if idx == 0 else 1
                    assert A[curr][entry_v] == 0, f"Duplicate edge {curr} -> {entry_v}"
                    A[curr][entry_v] = edge_wt
                    curr = exit_v
                assert A[curr][u_end] == 0, f"Duplicate edge {curr} -> {u_end}"
                A[curr][u_end] = 1

    return A


def run_tests():
    print("=== Test 1: General Grid Sum (|V|=2, |K|=2, |I|=3) over Z and F2 ===")
    v_map = [0, 0, 1]
    w_map = [0, 1, 1]
    W_mats = [
        [[2, -3], [5, 7]],
        [[1, 4], [-2, 3]],
        [[6, -1], [2, 5]],
    ]
    gt = eval_grid_sum(v_map, w_map, W_mats)
    M_perm = compile_grid_sum_to_perm(v_map, w_map, W_mats)
    p_val = permanent_ryser(M_perm)
    A_hc = compile_grid_sum_to_hc(v_map, w_map, W_mats)
    hc_val = hc_exact_dp(A_hc)
    print(f"  Ground truth = {gt}")
    print(f"  PERM ({len(M_perm)}x{len(M_perm)}) via Ryser = {p_val}")
    print(f"  HC   ({len(A_hc)}x{len(A_hc)}) via exact DP = {hc_val}")
    assert p_val == gt and Fraction(hc_val) == gt

    # Check mod 2 (where permanent FAILS because 1/2 does not exist, but HC SUCCEEDS!)
    gt_f2 = eval_grid_sum(v_map, w_map, W_mats, mod=2)
    hc_f2 = hc_exact_dp(A_hc, mod=2)
    print(f"  Over F2: ground truth = {gt_f2}, HC_M(mod 2) = {hc_f2}")
    assert hc_f2 == gt_f2
    print("[PASS] General grid sum matches PERM (char != 2) and HC (Z and F2)!\n")

    print("=== Test 2: Weighted #SAT / Clause Sum (Corollary E.2) ===")
    # 3 bits, 3 clauses with integer weights
    clauses = [
        ([(0, 1), (1, 0)], Fraction(3)),
        ([(1, 1), (2, 1)], Fraction(-2)),
        ([(0, 0), (2, 1)], Fraction(5)),
    ]
    gt_c = eval_clause_sum(3, clauses)
    vm, wm, Wm = clause_sum_to_grid_sum(3, clauses)
    M_c = compile_grid_sum_to_perm(vm, wm, Wm)
    p_c = permanent_ryser(M_c)
    # Integer weights for HC check
    Wm_int = [[[int(Wm[n][x][r]) for r in range(2)] for x in range(2)] for n in range(len(Wm))]
    A_c = compile_grid_sum_to_hc(vm, wm, Wm_int)
    hc_c = hc_exact_dp(A_c)
    print(f"  Clause sum literals q={len(vm)}, ground truth = {gt_c}")
    print(f"  PERM ({len(M_c)}x{len(M_c)}) via Ryser = {p_c}")
    print(f"  HC   ({len(A_c)}x{len(A_c)}) via exact DP = {hc_c}")
    assert p_c == gt_c and Fraction(hc_c) == gt_c
    print("[PASS] Weighted clause sum compiles cleanly to both PERM and HC!\n")

    print("=== Test 3: Network Polynomial f_{3,1} (2x2 Matrix Multiplication Trilinear Form) ===")
    # f_{3,1} = sum_{p,q,r in {0,1}} x_{1,pq} x_{2,pr} x_{3,qr}
    # Assign concrete integer values to the 3 * 4 = 12 variables x_{a, rho}
    rng = np.random.default_rng(2026)
    x_vals = {(a, b0, b1): int(rng.integers(-3, 5)) for a in (1, 2, 3) for b0 in (0, 1) for b1 in (0, 1)}
    # Direct evaluation of f_{3,1}
    f31_gt = sum(
        x_vals[(1, p, q)] * x_vals[(2, p, r)] * x_vals[(3, q, r)]
        for p in (0, 1) for q in (0, 1) for r in (0, 1)
    )
    # Build clause sum for f_{3,1}: 3 bits (p=0, q=1, r=2); 12 clauses of 2 literals each -> q = 24 literals
    # (For exact Ryser speed we'd have 3*24 = 72x72 which is too big for 2^72 Ryser,
    #  so we test BOTH: (a) HC exact DP on the FULL 24-literal f_{3,1} graph (~900 vertices?! Let's check!),
    #  AND (b) compact 6-literal grid-sum formulation of f_{3,1} for Ryser!)
    # First, direct grid-sum formulation of f_{3,1} using Prop E.1 directly (only 6 grid items, 18x18 matrix!):
    # Wait: let's test the FULL 12-clause / 24-literal clause sum via eval_clause_sum AND HC_DP!
    f31_clauses = []
    for b0 in (0, 1):
        for b1 in (0, 1):
            f31_clauses.append(([(0, b0), (1, b1)], Fraction(x_vals[(1, b0, b1)])))
            f31_clauses.append(([(0, b0), (2, b1)], Fraction(x_vals[(2, b0, b1)])))
            f31_clauses.append(([(1, b0), (2, b1)], Fraction(x_vals[(3, b0, b1)])))
    f31_clause_val = eval_clause_sum(3, f31_clauses)
    assert f31_clause_val == f31_gt
    vm3, wm3, Wm3 = clause_sum_to_grid_sum(3, f31_clauses)
    M_f31 = compile_grid_sum_to_perm(vm3, wm3, Wm3)
    Wm3_int = [[[int(Wm3[n][x][r]) for r in range(2)] for x in range(2)] for n in range(len(Wm3))]
    A_f31 = compile_grid_sum_to_hc(vm3, wm3, Wm3_int)
    print(f"  f_{{3,1}} ground truth = {f31_gt}, clause-sum eval = {f31_clause_val}")
    print(f"  Compiled f_{{3,1}} -> PERM matrix size {len(M_f31)}x{len(M_f31)}, HC graph size {len(A_f31)}x{len(A_f31)}")
    hc_f31 = hc_exact_dp(A_f31)
    hc_f31_f2 = hc_exact_dp(A_f31, mod=2)
    print(f"  HC ({len(A_f31)}x{len(A_f31)}) on FULL f_{{3,1}} = {hc_f31} (exact match!), mod 2 = {hc_f31_f2} (gt mod 2 = {f31_gt % 2})")
    assert hc_f31 == f31_gt and hc_f31_f2 == (f31_gt % 2)
    # Test a smaller network polynomial f_{2,1} = sum_{p in {0,1}} x_{1,p} x_{2,p} (4 clauses, 4 literals -> 12x12 PERM!)
    x2 = {(a, p): int(rng.integers(-4, 6)) for a in (1, 2) for p in (0, 1)}
    f21_gt = sum(x2[(1, p)] * x2[(2, p)] for p in (0, 1))
    f21_clauses = [([(0, p)], Fraction(x2[(a, p)])) for a in (1, 2) for p in (0, 1)]
    vm2, wm2, Wm2 = clause_sum_to_grid_sum(1, f21_clauses)
    M_f21 = compile_grid_sum_to_perm(vm2, wm2, Wm2)
    p_f21 = permanent_ryser(M_f21)
    Wm2_int = [[[int(Wm2[n][x][r]) for r in range(2)] for x in range(2)] for n in range(len(Wm2))]
    A_f21 = compile_grid_sum_to_hc(vm2, wm2, Wm2_int)
    hc_f21 = hc_exact_dp(A_f21)
    print(f"  f_{{2,1}} ground truth = {f21_gt} | PERM ({len(M_f21)}x{len(M_f21)}) = {p_f21} | HC ({len(A_f21)}x{len(A_f21)}) = {hc_f21}")
    assert p_f21 == f21_gt and hc_f21 == f21_gt
    print("[PASS] Network polynomials f_{2,1} and f_{3,1} compile and verify cleanly!")


if __name__ == "__main__":
    run_tests()
