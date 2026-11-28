# `quantum-cat0-checker` (`qcat0`)

A Python + **CVXPY** (SOCP / SDP / LP) verification and capacity-analysis tool applying **Theorem C.1** (*CAT(0) Curvature of Strassen's Asymptotic Spectrum*) and **Theorem A.6** (*Strassen Duality*) from *VP ≠ VNP Over Every Field* to multi-party quantum network topologies.

## Mathematical Foundation

Every spectral point $\phi$ in Strassen's asymptotic spectrum over any field $\mathbb{k}$ induces a wire price pseudometric $d_\phi(i, j) = \log_q \phi(\langle q \rangle_{ij})$ satisfying **Reshetnyak's / Berg–Nikolaev's 4-point CAT(0) quadrilateral cosine inequality** across all $3\binom{n}{4}$ ordered 4-tuples $(a,b,c,d)$:

$$\bigl|(d_{ac}^2 + d_{bd}^2) - (d_{ad}^2 + d_{bc}^2)\bigr| \;\le\; 2\, d_{ab}\, d_{cd}.$$

In squared-distance coordinates $u_{ij} = d_{ij}^2 \ge 0$, **both** the triangle inequalities ($u_{ik} - u_{ij} - u_{jk} \le 2\sqrt{u_{ij} u_{jk}}$) **and** all $3\binom{n}{4}$ Berg–Nikolaev inequalities ($|(u_{ac}+u_{bd}) - (u_{ad}+u_{bc})| \le 2\sqrt{u_{ab} u_{cd}}$) are **100% exact DCP-convex rotated second-order cone (SOCP) constraints** via `cvxpy.geo_mean` — with zero relaxation gap!

`qcat0` solves a 3-tier nested hierarchy for any multi-party quantum network:
1. **Metric Cone $\mathcal{M}_n$ (CVXPY SOCP / LP)** — triangle inequalities only (classical $L_1$/routing bound).
2. **Exact CAT(0) Cone $\mathcal{K}_{\mathrm{CAT(0)}, n}$ (CVXPY SOCP + lazy cutting planes for $n > 10$)** — enforces Theorem C.1 across all 4-tuples, estimating model-based asymptotic $L_2$-covering ebit budgets $\sqrt{s_{\mathrm{tot}}\, t_{\mathrm{tot}}\, \rho^*_{\mathrm{CAT(0)}}}$ via Strassen duality.
3. **Euclidean / Hilbert Cone $\mathcal{E}_n$ (CVXPY SDP)** — enforces Schoenberg's PSD Gram matrix $G \succeq 0$, exposing where non-Euclidean CAT(0) metrics (trees, hyperbolic spaces, rank metrics) strictly separate from flat Euclidean embeddings.

## Quick Start

From the repository root, install the tool and its numerical dependencies:
`python -m pip install ./quantum-cat0-checker`.


```bash
cd quantum-cat0-checker

# List built-in topologies
python -m quantum_cat0 list

# Analyze a specific topology (or custom JSON network)
python -m quantum_cat0 check C4_crossing
python -m quantum_cat0 check hypercube_Q3

# Run the full multi-topology CVXPY SOCP/SDP benchmark table
python -m quantum_cat0 benchmark

# Check a rational dual bound and export the corresponding integer inequality
python -m quantum_cat0 certify hypercube_Q3 --lean-out Q3Cert.lean
python -m quantum_cat0 certify K23_bipartite
```


### Interpreting single-restriction results

`FORBIDDEN_BY_CUT` includes a concrete bipartition witness. `CAT0_CANDIDATE` reports a sampled four-point metric with ratio below one whose spectral realization is unknown. `METRIC_LP_GAP` reports a relaxed LP ratio below one when the geometric search found no such candidate. The candidate ratio is the lowest value observed during that search. JSON exposes it as `cat0_candidate_ratio` and retains the historical `cat0_spectral_ratio` alias.

Exact Enflo certificates use rational EPR weights throughout the final check and Lean export. The denominator limit applies to proposed dual multipliers. JSON decimal weights are parsed before conversion to floating-point solver coefficients.

The numerical solver proposes a dual witness. The Python verifier checks its rational
coefficients and every edge slack exactly. The historical JSON field `exact_rho_enflo`
is a certified upper bound under the modeled constraints, not a claim of optimality;
a matching primal witness is not produced. The standalone Lean export checks a
denominator-cleared inequality for integer edge variables under its stated
nonnegativity and geometry assumptions. It does not itself certify real-valued
premises or optimality.

Numerical verdicts use rates relative to a common unit and validate four-point candidates at unit diameter. Covering budgets are reported in the original units. The covering flag compares a numerical model estimate with the available budget: `true` or `false` requires a resolved relative margin; `null` indicates an inconclusive comparison or omitted covering analysis. A numerical budget estimate alone does not certify a covering protocol.
