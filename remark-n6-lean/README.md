# Remark N.6 — Lean 4.33.1 Formalization (Border Determinantal Complexity)

This folder contains our standalone Lean 4.33.1 formalization of **Remark N.6 ("determinantal complexity")** from Anthropic's paper *"VP ≠ VNP Over Every Field"*, closing the one numbered statement that was not formalized in the original [`anthropics/formal-math`](https://github.com/anthropics/formal-math) (`vp-vnp`) development.

## Files

- [`RemarkN6.lean`](./RemarkN6.lean) — 891 lines, zero `sorry`, zero warnings:
  - Multi-output straight-line arithmetic circuits (`RemarkN6.Circ`) lowering directly into `Statement.Computes`.
  - Division-free **Samuelson–Berkowitz** polynomial-size determinant circuit over arbitrary commutative rings via `PowerSeries` Neumann series and unit-determinant block lower-triangularization (avoiding `Matrix.inv` and `IsUnit` entirely).
  - Explicit circuit-size bound `computes_det_of_affine`: every $k \times k$ affine matrix in $|V|$ variables has an arithmetic circuit of size $k^2(4|V| + 2) + 10(k + 1)^4 + 2$ computing $\det(M)$.
  - `remarkN6_of_mainTheoremApprox`: composes the determinant circuit with `Statement.MainTheoremApprox` to prove superpolynomial border determinantal complexity for $\mathrm{PERM}_m$ over every field of characteristic $\neq 2$.
- [`scripts/CheckRemarkN6.lean`](./scripts/CheckRemarkN6.lean) — standalone axiom check for `RemarkN6.computes_det_of_affine` and `RemarkN6.remarkN6_of_mainTheoremApprox`.
- [`scripts/CheckFullVerification.lean`](./scripts/CheckFullVerification.lean) — unconditional composition `remarkN6_unconditional := RemarkN6.remarkN6_of_mainTheoremApprox Solution.mainTheoremApprox` plus `#print axioms` on all 5 headline theorems of `Solution` and `remarkN6_unconditional`.

## Verified Axioms (Lean 4.33.1)

After building all 323/323 modules of `anthropics/formal-math/vp-vnp` locally (9,032 Lake jobs, 72,932 lines, zero `sorry` warnings in `Solution`/`Paper`), running `lake env lean scripts/CheckFullVerification.lean` exits with code `0`, zero warnings, and prints:

```text
'Solution.mainTheorem' depends on axioms: [propext, Classical.choice, Quot.sound]
'Solution.separation' depends on axioms: [propext, Classical.choice, Quot.sound]
'Solution.mainTheoremApprox' depends on axioms: [propext, Classical.choice, Quot.sound]
'Solution.separationClosure' depends on axioms: [propext, Classical.choice, Quot.sound]
'Solution.permanent_over_real' depends on axioms: [propext, Classical.choice, Quot.sound]
'remarkN6_unconditional' depends on axioms: [propext, Classical.choice, Quot.sound]
```

## How to Reproduce Against `anthropics/formal-math`

1. Clone [`anthropics/formal-math`](https://github.com/anthropics/formal-math) (Apache-2.0) and fetch its Mathlib cache inside `formal-math/vp-vnp`:
   ```bash
   git clone https://github.com/anthropics/formal-math.git
   cd formal-math/vp-vnp
   lake exe cache get
   ```
2. Copy the files from this directory into `formal-math/vp-vnp/`:
   ```bash
   cp ../../remark-n6-lean/RemarkN6.lean ./RemarkN6.lean
   mkdir -p scripts
   cp ../../remark-n6-lean/scripts/CheckRemarkN6.lean ./scripts/
   cp ../../remark-n6-lean/scripts/CheckFullVerification.lean ./scripts/
   ```
3. Verify `RemarkN6.lean` against `Statement.lean` (takes ~1 minute):
   ```bash
   lake build Statement
   lake env lean scripts/CheckRemarkN6.lean
   ```
4. For the full unconditional check (all 323 modules), build `Solution` (on Windows / low-RAM machines, use `../../scripts/build_lean_batched.py 1` or [`lean-build-orchestrator`](../lean-build-orchestrator/)) and run:
   ```bash
   lake env lean scripts/CheckFullVerification.lean
   ```

## Attribution & License

`RemarkN6.lean` builds on `Statement.lean` and `Solution.lean` from [`anthropics/formal-math`](https://github.com/anthropics/formal-math) (licensed under Apache-2.0). All original files in this directory are likewise licensed under Apache-2.0.
