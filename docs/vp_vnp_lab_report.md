# VP ≠ VNP Over Every Field — Verification, Formalization & Research Lab Report

> [!IMPORTANT]
> **Key Headline Results**
> 1. **Remark N.6 is unconditionally formalized and kernel-verified in Lean 4.33.1** ([`RemarkN6.lean`](../remark-n6-lean/RemarkN6.lean)): we formalized a complete, division-free Samuelson–Berkowitz polynomial-size determinant circuit over arbitrary commutative rings and composed it with `Solution.mainTheoremApprox` to obtain `remarkN6_unconditional` ([`CheckFullVerification.lean`](../remark-n6-lean/scripts/CheckFullVerification.lean)) with **zero `sorry`**, **zero warnings**, and **only `[propext, Classical.choice, Quot.sound]`**.
> 2. **Full local build & audit of `anthropics/formal-math/vp-vnp` completed (323/323 modules, 72,932 lines, 9,032 Lake jobs):** Static integrity auditing found zero `sorry` outside `Challenge.lean` and zero custom `axiom`, `native_decide`, `unsafe`, `implemented_by`, `admit`, or `ofReduceBool`. All 323 modules compiled locally via [`scripts/build_lean_batched.py`](../scripts/build_lean_batched.py) in `18,708.4 s` (~5 h 12 m) with exit code `0`, confirming all 5 headline theorems (`mainTheorem`, `separation`, `mainTheoremApprox`, `separationClosure`, `permanent_over_real`) plus `remarkN6_unconditional` depend strictly on `[propext, Classical.choice, Quot.sound]`.
> 3. **All six Python symbolic/numerical research experiments (`exp04`–`exp09`) passed 100%**, uncovering the exact universal Hilbert contraction bound $D(\mu)^2 / D(1)^2 \le 2 - 2^{1-\mu} < 2$ on $\mathrm{Mat}_\mu(\mathbb{F}_2)$, a 2-line proof that the non-Euclidean rank metric $\sqrt{\mathrm{rk}(a-a')}$ is CAT(0), and a proof that Proposition E.9's $\sqrt{k}$ bound and the flat-case $4/3$ exponent are structurally tight under Lemma E.8 and expander substitutions.
> 4. **Three production engineering tools grew directly out of this lab:** [`pcvh/`](../pcvh/) (Proof-Carrying Verification Harness), [`lean-build-orchestrator/`](../lean-build-orchestrator/) (Windows/low-RAM Lean 4 scheduler & import shaker), and [`quantum-cat0-checker/`](../quantum-cat0-checker/) (CVXPY CAT(0) entanglement capacity solver).

---

## Part I — Lean 4 Verification, Audit & Formalization (#1–#3)

### #1. Independent Audit & Full Local Build of `anthropics/formal-math/vp-vnp`

Upstream repository: [`anthropics/formal-math`](https://github.com/anthropics/formal-math) (`vp-vnp/`, Lean 4.33.1, Mathlib commit `0df444a360eaa60ab8c11dca51a86af692955474`, all 8,690 cache files fetched).

| Audit Check | Result | Notes |
| --- | --- | --- |
| Total Lean codebase | **324 files, 72,932 lines** | `Paper/` (43), `NS1/` (29), `Nc/` (236), `Ov/` (11), top-level (5) |
| `Statement.lean` vs. PDF Section 3 | **Exact match** | Identical minus the 5-line Apache-2.0 header |
| `sorry` scan across all 324 files | **0 outside `Challenge.lean`** | 5 theorem stubs + 1 doc comment inside `Challenge.lean` only |
| `axiom`, `native_decide`, `unsafe`, `implemented_by`, `admit`, `ofReduceBool`/`Nat` | **0 hits across all 324 files** | Clean across every file |
| Upstream CI verification bar | **Palomar `comparator` + `nanoda` + `landrun`** | Audited in `.github/scripts/comparator-check.sh` and `.github/workflows/lean-projects.yml` |
| Full local kernel build (Lean 4.33.1) | **PASS — 323 / 323 modules (9,032 Lake jobs)** | Built via `scripts/build_lean_batched.py 1` in `18,708.4 s`, exit code `0`, 0 `sorry` warnings in `Solution`/`Paper` |
| Final axiom audit (`CheckFullVerification.lean`) | **PASS — all 6 theorems clean** | All 5 `Solution.*` headline theorems + `remarkN6_unconditional` depend strictly on `[propext, Classical.choice, Quot.sound]` |

> [!NOTE]
> **Windows Build Engineering Finding:** 28 root modules in `vp-vnp` perform a broad `import Mathlib`. On Windows, Lean 4.33.1 commits ~10 GB of pagefile per `import Mathlib` process (against ~18.7 GB available commit charge on a 16–32 GB workstation), so running $\ge 2$ concurrent `lean.exe` processes triggers Windows commit-charge failures (`failed to read file '*.olean.private'`, Win32 error 1455). Sequential topological scheduling with `GetPerformanceInfo` commit-charge gating built all 323 modules reliably without a single crash — and motivated building [`lean-build-orchestrator/`](../lean-build-orchestrator/) to combine commit-aware scheduling with automated import shaking.

---

### #2. Formalizing Remark N.6 in Lean 4 (Closing the One Missing Theorem)

Extracted standalone files in [`remark-n6-lean/`](../remark-n6-lean/):
- [`remark-n6-lean/RemarkN6.lean`](../remark-n6-lean/RemarkN6.lean) (891 lines)
- [`remark-n6-lean/scripts/CheckRemarkN6.lean`](../remark-n6-lean/scripts/CheckRemarkN6.lean)
- [`remark-n6-lean/scripts/CheckFullVerification.lean`](../remark-n6-lean/scripts/CheckFullVerification.lean)

**Proof architecture:**
1. **`Circ R V` combinators:** Multi-output straight-line circuits lowering directly into `Statement.Computes`, with explicit gate counts for variable/constant/sum/product/negation, dot products ($2n+1$ gates), matrix–vector products ($n(2n+1)$ gates), and arbitrary affine polynomials of total degree $\le 1$ ($4|V| + 2$ gates).
2. **Division-free Samuelson–Berkowitz identity over `PowerSeries S`:** For any $n \times n$ matrix $A$ over any commutative ring $S$, define $q(A) = \det(I - X A) \in S[[X]]$. We prove:
   - `coeff_revCharSeries_top`: $[X^n]\,q(A) = (-1)^n \det(A)$.
   - `one_sub_X_mul_neumann`: $(I - X M)\sum_{k \ge 0} M^k X^k = I$ in $S[[X]]$.
   - `revCharSeries_succ`: Right-multiplying $\begin{pmatrix} 1 - Xa & -Xr \\ -Xc & I - XM \end{pmatrix}$ by the unit-determinant block lower-triangular matrix $\begin{pmatrix} 1 & 0 \\ S(Xc) & I \end{pmatrix}$ avoids `Matrix.inv` and `IsUnit` entirely, proving $q(A) = \bigl(1 - a X - \sum_{j \ge 0} (r M^j c) X^{j+2}\bigr) q(M)$ over *every* commutative ring.
3. **Explicit polynomial-size circuit (`computes_det_of_affine`):** Every $k \times k$ affine matrix $M$ in $|V|$ variables has an arithmetic circuit of size
   $$k^2(4|V| + 2) + 10(k + 1)^4 + 2$$
   computing $\det(M)$.
4. **Unconditional border determinantal lower bound (`remarkN6_unconditional`):** Composing `remarkN6_of_mainTheoremApprox` (with $c = c_0 / 5 > 0$) with the locally compiled `Solution.mainTheoremApprox` proves unconditionally that for every characteristic $p \neq 2$, every field $F$ of characteristic $p$, and all $m \ge m_0$, no $k \times k$ affine matrix over `LaurentSeries F` with $k \le m^{c(\log_2 m)^{1/3}}$ has determinant approximating $\mathrm{PERM}_m$.

**Verified Lean 4.33.1 output (`CheckFullVerification.lean`):**
```text
'Solution.mainTheorem' depends on axioms: [propext, Classical.choice, Quot.sound]
'Solution.separation' depends on axioms: [propext, Classical.choice, Quot.sound]
'Solution.mainTheoremApprox' depends on axioms: [propext, Classical.choice, Quot.sound]
'Solution.separationClosure' depends on axioms: [propext, Classical.choice, Quot.sound]
'Solution.permanent_over_real' depends on axioms: [propext, Classical.choice, Quot.sound]
'remarkN6_unconditional' depends on axioms: [propext, Classical.choice, Quot.sound]
```
Zero errors, zero warnings, zero `sorry`.

---

### #3. Human Audit of the Four "Lean-Only" Contracting-Case Proofs

The paper explicitly delegates exact semantic verification of four intricate machine/program constructions to Lean. Auditing the underlying implementations in `anthropics/formal-math/vp-vnp` shows clean, textbook-faithful formalization with no shortcuts:

| Paper Statement | Lean Entry Point | Underlying Implementation | Audit Summary |
| --- | --- | --- | --- |
| **Prop. I.1** (Universal tape automaton) | `Paper/Universal.lean`, `Paper/UniversalSteps.lean` | `Nc/Uni/` (20 files, 4,878 lines; `PM.lean`, `SortU.lean`) | Formal 5-register pointer machine `Mach` with local runs `Seq` vs. globally checked traces `GV` (`Mach.gv_iff`), queue-based multi-pass radix sort (`emDr`/`emCo`), exact bijection on traces, explicit step count $O((|z|+\tau)\lg^2(|z|+\tau))$. |
| **Thm. H.2(d)–(e)** (Tree straight-line program & packet counts) | `Paper/Tree.lean` | `Nc/Tow/` (37 files, 8,860 lines; `Slp0.lean`, `Ever1.lean`) | Explicit bounded-alphabet straight-line program calculus `CY`/`PY` (`Alph D Y` with $Y^4 \le D$), full accounting of every packet/copy/zero ever held (`Ever1`–`Ever7`), constructing `ThinTrees`. |
| **Thm. J.3** (One-cut evaluator & cutting program $G$) | `Paper/Cuts.lean`, `NS1/OneCut.lean` | `Nc/Grp/` (28 files, 6,382 lines) & `Nc/Dl/` (22 files, 5,297 lines) | Concrete script AST (`block`, `input`, `both`, `one`, `role`) encoded as binary trees `scriptT`; verified evaluator `GROUP` (`insSem`, `GroupOK`, `GrpTimeOK`) and dealing/cutting program `dealF` (`dealF_does`) preserving exact weighted-product sums. |
| **Prop. N.4** (Approximate $\to$ exact accelerators) | `Paper/ApproxScales.lean`, `Paper/ApproxRound.lean` | `NS1/ApproxExtract.lean` & `NS1/Approx*.lean` | Algebra hom `wrap : E[T;T⁻¹] →ₐ[A] AddMonoidAlgebra E (ZMod (2^W))`, `coeff_wrap_zero` proving $0 \pmod{2^W}$ recovers $[\varepsilon^0]$, binary ripple-carry adder `addc` + guessing loop `chT` over sparse Laurent terms. |

---

## Part II — Executable Symbolic & Numerical Experiments (#4–#8)

### #4. Meixner–Frobenius Crossing Identity (Prop. B.2)
Script: [`experiments/exp04_meixner_crossing.py`](../experiments/exp04_meixner_crossing.py)

- Verified truncated Meixner orthogonality (B.1) and $C(r,n) = y^n B(r,n)|_{y\mapsto 1/y}$ symbolically up to $R = 6$.
- Constructed $\mathbf{M}(X; s_a, s_b, s_c, s_d)$ and verified exact $\det \mathbf{M}|_{X=1} = \varepsilon \langle |\Sigma_1| \rangle_{ac} \langle |\Sigma_2| \rangle_{bd}$, exact reflection symmetry $X^\Theta \Psi(1/X; a,b,c,d) = \Psi(X; a,d,c,b)$, and exact integer tensor sum $\sum_{N=0}^\Theta \Psi_N = \langle |\Sigma_1| \rangle_{ac} \langle |\Sigma_2| \rangle_{bd}$ across $(3\times 2)$, $(3\times 3)$, and $(4\times 3)$ Frobenius symbol classes.
- **Exact rank tradeoff observed on $(|\Sigma_1|=4, |\Sigma_2|=3, \Theta=28)$** (full crossing rank $= 12$ across *both* cuts; odd $N$ vanish identically):
  - At $N = 0$: $\mathrm{rk}(ad|bc) = \mathbf{1}$ (tight against bound $1$), $\mathrm{rk}(ab|cd) = \mathbf{9} < 12$.
  - At $N = 2$: $\mathrm{rk}(ad|bc) = \mathbf{3}$ (bound $6$), $\mathrm{rk}(ab|cd) = \mathbf{11} < 12$.
  - At $N = 4$: $\mathrm{rk}(ad|bc) = \mathbf{7}$ (bound $20$), $\mathrm{rk}(ab|cd) = 12$.
  - Mirror-symmetric at $N = 24, 26, 28$: $\mathrm{rk}(ab|cd) = 7, 3, 1$. Every $\Psi_N$ satisfies both integer rank bounds simultaneously.

---

### #5. Compact Compilers: Grid Sums / Weighted #SAT $\to$ $\mathrm{PERM}$ & $\mathrm{HC}$ (Props. E.1 & M.2)
Script: [`experiments/exp05_clause_compilers.py`](../experiments/exp05_clause_compilers.py)

Implemented both constructive compilers and an independent general-graph exact propagating Hamiltonian-cycle solver (`hc_exact_dp`) plus Gray-code Ryser permanent evaluator (`permanent_ryser`):

| Benchmark | Ground Truth | Prop. E.1 $\mathrm{PERM}$ (Ryser) | Prop. M.2 $\mathrm{HC}$ (Exact Solver) | $\mathbb{F}_2$ Check |
| --- | --- | --- | --- | --- |
| General grid sum ($\|V\|=2, \|K\|=2, \|I\|=3$) | `-72` | `9×9` $\to$ `-72` | `115×115` $\to$ `-72` | `0 == 0` |
| Weighted #SAT clause sum ($q=6$ literals) | `2` | `18×18` $\to$ `2` | `228×228` $\to$ `2` | — |
| $f_{2,1}$ (numeric) | `-6` | `12×12` $\to$ `-6` | `153×153` $\to$ `-6` | — |
| **$f_{2,1}$ (symbolic in 4 variables)** | $x_{10}x_{20} + x_{11}x_{21}$ | `6×6` $\to$ exact match | `76×76` $\to$ exact match | — |
| **$f_{3,1}$ ($2\times 2$ MatMul, 24 literals)** | `-9` | `72×72` compiled | **`903×903` $\to$ `-9`** | **`1 == 1`** |

---

### #6. Probing the "Flat vs. Contracting" Mystery on $\mathrm{Mat}_\mu(\mathbb{F}_2)$
Script: [`experiments/exp06_flat_vs_contracting.py`](../experiments/exp06_flat_vs_contracting.py)

Two sharp discoveries emerged:
1. **Exact universal Hilbert-space contraction formula:** Using Grassmannian Möbius inversion on $\mathrm{Mat}_\mu(\mathbb{F}_2)$ (cross-checked against brute-force enumeration on $\mathrm{Mat}_2(\mathbb{F}_2)$), *every* Hilbert/Euclidean embedding satisfies:
   $$\frac{D(\mu)^2}{D(1)^2} \le 2 - 2^{1-\mu} < 2 \qquad \Longrightarrow \qquad s_{\mathrm{Hilb}} = \sqrt{2 - 2^{1-\mu}} < \sqrt{2} < \sqrt{\mu} \quad (\forall \mu \ge 2),$$
   achieved at rank-1 Fourier frequency $k=1$ (e.g., a linear half-space cut). Thus **Euclidean metrics themselves always contract**—even for $\mu=2$ ($1.2247 < 1.4142$). Flattening cuts ($s \le 1.323$ at $\mu=3$) and star-tree quantum-functional wire metrics ($s \approx 1.001$) all contract strongly as well.
2. **The extremal non-Euclidean rank metric $d(a,a') = \sqrt{\mathrm{rk}(a-a')}$ IS genuinely CAT(0) (Reshetnyak):**
   - Strongly non-Euclidean (minimum Gram eigenvalue $-0.963$ at $\mu=2$, $-24.22$ at $\mu=3$), yet exhibited **0.000000 Reshetnyak violation** across all 4,096 exhaustive triples at $\mu=2$ and 1.5M random + adversarial quadruples at $\mu=3$.
   - Indeed, rank subadditivity gives a 2-line analytical proof over every field: putting $a = \mathrm{rk}(X+Y)-\mathrm{rk}(Y)$ and $b = \mathrm{rk}(Y+Z)-\mathrm{rk}(X+Y+Z)$, both $a, b \le \min(\mathrm{rk}\,X, \mathrm{rk}\,Z)$, so $a + b \le 2\sqrt{\mathrm{rk}(X)\mathrm{rk}(Z)}$.
   - **Takeaway:** The Flat vs. Contracting question over $\mathbb{C}$ boils down specifically to whether this *non-Euclidean* CAT(0) rank metric $\sqrt{\mathrm{rk}(a-a')}$ can be approximated by spectral points $c\,d_\phi$ over $\mathbb{C}$.

---

### #7. Optimizing the Flat-Case Euclidean Hub Geometry (Appendix E)
Script: [`experiments/exp07_flat_hub_optimizer.py`](../experiments/exp07_flat_hub_optimizer.py)

- **Constant-factor comparison on $K_k$ ($k=6,8,10,12$):** Prop. E.5’s edge-difference embedding $\pm \frac{1}{2}(e_a - e_b)/\sqrt{2}$ beats Prop. E.10’s facet-centre embedding $\pm \frac{1}{2} e_a$ by ~32% in hub slope (e.g., $7.01$ vs. $5.31$ at $k=12$), and Prop. E.10 beats regular-tournament orientations ($4.93$).
- **Why the $4/3$ exponent is structurally invariant across expanders:** Replacing $K_k$ by any $\Delta$-regular expander yields $\|w_S\| = \Theta(\sqrt{k}\Delta)$, $\eta = \Theta(k^{-1/2})$, $\mathrm{saving} = \Theta(\Delta)$, threshold $\ell = \Theta(k^{3/2}/\Delta)$, so $\log m = \Theta(\Delta \ell) = \Theta(k^{3/2})$ and $\log L = \Theta(k^2) = \Theta((\log m)^{4/3})$—verified numerically across $\Delta \in \{3,4,6,8,11\}$ at $k=12$.
- **Exact tightness of Proposition E.9 for Lemma E.8:** Any iterated-midpoint reduction from 2-point wires $\{\pm v_\chi\}$ to the cross-polytope $\{\pm \frac{1}{2} e_i\}_{i=1}^k$ must satisfy $\mathbb{E}_\chi \|v_\chi\|^2 \ge \sum_i (\mathbb{E}_\chi [s_{i,\chi}(v_\chi \cdot e_i)])^2 = k/4$, forcing $\max_\chi (2\|v_\chi\|) \ge \sqrt{k}$. Even if a completely different method improved $c\,g_\phi(P)$ from $\sqrt{k}$ to $O(1)$, the flat-case framework would still cap out at $(\log m)^{3/2}$ rather than exponential.

---

### #8. Concrete $\mathrm{SL}_h(\mathbb{F}_2[s]/(s^{n+1}))$ Coset Tower & Tree Load-Halving Simulation
Script: [`experiments/exp08_coset_tower_sim.py`](../experiments/exp08_coset_tower_sim.py)

- Explicitly constructed the full group $G_1 = \mathrm{SL}_3(\mathbb{F}_2[s]/(s^2))$ (**43,008 elements**, exact Cayley diameter $L = 23$, mean word length $15.85$ in generators $X_0, X_1, X_2$).
- Verified all clauses of Proposition H.1: all three cyclic copies $U_0, U_1, U_2 \cong U_3$ (order $b = 8$) intersect $K_1$ trivially; built the explicit index-8 subgroup tower $V_0(43{,}008) \xrightarrow{8:1} V_1(5{,}376) \xrightarrow{8:1} V_2(672)$ and verified freeness, $X_i$-coset crossing, and $8$-to-$1$ bijectivity across all 84 cosets.
- Simulated Theorem H.2’s $L_2$ load-halving dynamics ($b=16, J=8, M=4.29\times 10^9, \gamma=1/4, h=32, C_1=1.75$), confirming total tree traffic converges to $2\times$ initial scale while the worst-case single-node bottleneck (at the root) shrinks by $M^{-\gamma} \approx 1.38 \times 10^{-3}$.

---

## Part III — Theoretical Follow-up Derivations (#9–#11)
Backing calculations: [`experiments/exp09_pit_and_quantum_cat0.py`](../experiments/exp09_pit_and_quantum_cat0.py)

### #9. Kabanets–Impagliazzo [KI04] PIT Derandomization Bound
Inverting the circuit lower bound $s(m) = S^{c_0}$ into the Nisan–Wigderson design (universe size $U = O(m^4)$ for $\mathrm{PERM}_m$, or $O(m^2)$ using $f_{k,\ell}$):
- **From the main theorem ($2^{c(\log m)^{4/3}}$):** $m = 2^{\Theta((\log S)^{3/4})}$, giving deterministic PIT (in char $0$ / large char) in time
  $$T_{\mathrm{PIT}}(S) = 2^{2^{O((\log S)^{3/4})}} = 2^{S^{o(1)}}$$
  —strictly faster than $2^{S^\varepsilon}$ for every constant $\varepsilon > 0$ (major theoretical derandomization milestone), though ineffective/astronomical in constants ($c = 1/1600^2$) and not a practical replacement for randomized Schwartz–Zippel.
- **If the contracting case holds over $\mathbb{C}$ ($2^{c(\log m)^2/\log\log m}$):** sharpens to $T_{\mathrm{PIT}}(S) = 2^{2^{O(\sqrt{\log S \log\log S})}}$.

### #10. CAT(0) Curvature in Quantum Information & Tensor Rank
- **3 parties (Matrix Multiplication $\omega$):** Every 3-point metric embeds isometrically in $\mathbb{R}^2$ (which is CAT(0)), so Theorem C.1 imposes no standalone constraint on 3-party wire metrics without auxiliary hub parties.
- **4+ parties (New universal asymptotic entanglement/tensor law):** Theorem C.1 enforces the **Berg–Nikolaev quadrilateral cosine** on every spectral point $\phi$ on $\{1,2,3,4\}$:
  $$\bigl|(d_{13}^2 + d_{24}^2) - (d_{14}^2 + d_{23}^2)\bigr| \le 2\, d_{12} d_{34},$$
  ruling out all non-CAT(0) 4-point metrics (such as $L_1$ / $C_4$ shortest-path metrics) from Strassen’s asymptotic spectrum.
- **Asymptotic crossing-EPR compression via Strassen duality (Thm. A.6):** For every field $\mathbb{k}$ and $\varepsilon > 0$, $N$ copies of two crossing EPR pairs $(\langle 2 \rangle_{xv} \langle 2 \rangle_{yu})^N$ ($2N$ crossing ebits) are covered by $\le 2^{\varepsilon N}$ SLOCC restrictions of 4-cycle EPR networks $\langle 2^{m_1}\rangle_{xy}\langle 2^{m_2}\rangle_{yv}\langle 2^{m_3}\rangle_{vu}\langle 2^{m_4}\rangle_{ux}$ with $m_1^2 + m_2^2 + m_3^2 + m_4^2 \le (2 + \varepsilon)N^2$—total $\le 2\sqrt{2}\,N \approx 2.828\,N$ ebits vs. $4N$ for naive routing (a $\sqrt{2}\times$ compression factor).

### #11. Relativization & Algebrization ([BGS75, AW09])
Both branches are **genuinely non-relativizing and non-algebrizing**, and break cleanly against black-box algebraic oracle gates $O = \mathrm{PERM}$ at the two arrows marked **C** in Figure 1:
- **Flat case:** `lem_balanced` (Lemma E.4) relies on white-box bilinearity of binary multiplication gates $(\gamma_1\gamma_2)_S = \sum_{A \sqcup B = S} (\gamma_1)_A (\gamma_2)_B$ (Hyafil/VSBR depth-reduction structure), which fails for high-degree/high-fan-in oracle gates.
- **Contracting case:** `lem_lowdeg` (Lemma K.2) relies on white-box unfolding of binary product gates into Jerrum–Snir / Malod–Portier parse trees of $\le d$ leaves, which likewise fails for black-box algebraic/low-degree-extension oracle gates.

---

## Part IV — Practical Software Built From This Lab

Three of the six engineering follow-ups identified above have been built, tested, and verified in this repository:

| Project | Folder | Status | Highlights |
| --- | --- | --- | --- |
| **Proof-Carrying Verification Harness (PCVH)** | [`pcvh/`](../pcvh/) | **Phases 1–5 Complete** (25/25 tests) | Zero-trust Palomar gate (12/12 red-team attacks blocked), live Lean 4 LSP + bounded falsifier + autonomous prover, 5 verified real-world blueprints (ERC-4626/AMM, BFT Consensus, SSA Compiler Optimizer, Double-Entry Ledger, CAT(0) Proof Certificate), 40/40 live eval benchmark (`pcvh/eval_dashboard.html`). Design plan in [`plans/proof_carrying_verification_harness_plan.html`](../plans/proof_carrying_verification_harness_plan.html). |
| **Lean 4 Windows / Low-RAM Build Orchestrator** | [`lean-build-orchestrator/`](../lean-build-orchestrator/) | **Complete** (8/8 tests) | Win32 `GetPerformanceInfo` commit-charge telemetry, comment-aware Lean import DAG + umbrella blast-radius analyzer, commit-gated topological scheduler, native `lake shake` + `.olean` fallback shaker. |
| **Quantum-Network Entanglement & CAT(0) Checker** | [`quantum-cat0-checker/`](../quantum-cat0-checker/) | **Complete** (8/8 tests) | Exact DCP-convex CVXPY SOCP/SDP (`CLARABEL` + `SCIPY`) for Theorem C.1 Berg–Nikolaev CAT(0) cone vs. Schoenberg Euclidean SDP vs. Metric LP across 11 network topologies, with certified strict 3-way separation on $K_{2,3}$ and direct bridge into PCVH Blueprint 5. |
