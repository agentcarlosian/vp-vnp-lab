# `quantum-cat0-checker` (`qcat0`)

A Python + **CVXPY** (SOCP / SDP / LP) verification and capacity-analysis tool applying **Theorem C.1** (*CAT(0) Curvature of Strassen's Asymptotic Spectrum*) and **Theorem A.6** (*Strassen Duality*) from *VP ≠ VNP Over Every Field* to multi-party quantum network topologies.

## Mathematical Foundation

Every spectral point $\phi$ in Strassen's asymptotic spectrum over any field $\mathbb{k}$ induces a wire price pseudometric $d_\phi(i, j) = \log_q \phi(\langle q \rangle_{ij})$ satisfying **Reshetnyak's / Berg–Nikolaev's 4-point CAT(0) quadrilateral cosine inequality** across all $3\binom{n}{4}$ ordered 4-tuples $(a,b,c,d)$:

$$\bigl|(d_{ac}^2 + d_{bd}^2) - (d_{ad}^2 + d_{bc}^2)\bigr| \;\le\; 2\, d_{ab}\, d_{cd}.$$

In squared-distance coordinates $u_{ij} = d_{ij}^2 \ge 0$, **both** the triangle inequalities ($u_{ik} - u_{ij} - u_{jk} \le 2\sqrt{u_{ij} u_{jk}}$) **and** all $3\binom{n}{4}$ Berg–Nikolaev inequalities ($|(u_{ac}+u_{bd}) - (u_{ad}+u_{bc})| \le 2\sqrt{u_{ab} u_{cd}}$) are **100% exact DCP-convex rotated second-order cone (SOCP) constraints** via `cvxpy.geo_mean` — with zero relaxation gap!

`qcat0` solves a 3-tier nested hierarchy for any multi-party quantum network:
1. **Metric Cone $\mathcal{M}_n$ (CVXPY SOCP / LP)** — triangle inequalities only (classical $L_1$/routing bound).
2. **Exact CAT(0) Cone $\mathcal{K}_{\mathrm{CAT(0)}, n}$ (CVXPY SOCP + lazy cutting planes for $n > 10$)** — enforces Theorem C.1 across all 4-tuples, certifying exact asymptotic $L_2$-covering ebit budgets $\sqrt{s_{\mathrm{tot}}\, t_{\mathrm{tot}}\, \rho^*_{\mathrm{CAT(0)}}}$ via Strassen duality.
3. **Euclidean / Hilbert Cone $\mathcal{E}_n$ (CVXPY SDP)** — enforces Schoenberg's PSD Gram matrix $G \succeq 0$, exposing where non-Euclidean CAT(0) metrics (trees, hyperbolic spaces, rank metrics) strictly separate from flat Euclidean embeddings.

## Quick Start

```bash
cd quantum-cat0-checker

# List built-in topologies
python -m quantum_cat0 list

# Analyze a specific topology (or custom JSON network)
python -m quantum_cat0 check C4_crossing
python -m quantum_cat0 check hypercube_Q3

# Run the full multi-topology CVXPY SOCP/SDP benchmark table
python -m quantum_cat0 benchmark

# Extract exact rational Farkas dual certificate & standalone zero-sorry Lean 4 proof
python -m quantum_cat0 certify hypercube_Q3 --lean-out Q3Cert.lean
python -m quantum_cat0 certify K23_bipartite
```
