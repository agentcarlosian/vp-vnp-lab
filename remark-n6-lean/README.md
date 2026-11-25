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

Run these commands from the root of your `vp-vnp-lab` clone. Prerequisites:
Git, Python 3.11+, [elan](https://github.com/leanprover/elan) on `PATH`, and
enough disk space for Lean and the Mathlib cache. The commands use a **disposable**
sibling checkout, not your existing upstream working tree.

```sh
git init ../formal-math-n6
git -C ../formal-math-n6 fetch --depth=1 https://github.com/anthropics/formal-math.git 11b6c7e3c927df2658f513b6b68ea7f8929c62c5
git -C ../formal-math-n6 checkout --detach FETCH_HEAD
python remark-n6-lean/reproduce.py ../formal-math-n6
```

This is the reproduction pin, not a claim about the exact upstream checkout
used in the earlier local report. It uses Lean 4.33.1 and the same Mathlib
revision recorded in that report.

The helper fetches the pinned Mathlib cache, copies the extension and both check
scripts into the disposable checkout's `vp-vnp/` directory, builds `Statement`,
then explicitly compiles `RemarkN6.lean` to
`.lake/build/lib/lean/RemarkN6.olean` before running `CheckRemarkN6.lean`.
It checks the reported axioms for the determinant construction and the
**conditional** Remark N.6 theorem. The [Ubuntu smoke workflow](../.github/workflows/remark-n6.yml)
runs this short check without building `Solution`.

For the **full composition**, use `--full` to build `Solution` and run
`CheckFullVerification.lean` as well. This may be a long build.

```sh
python remark-n6-lean/reproduce.py ../formal-math-n6 --full --skip-cache
```

Use `--skip-cache` only after successfully fetching the Mathlib cache in that
checkout. On Windows or a memory-constrained system, add `--batch-size 1` to
the full command. That sets `VP_VNP_DIR` to the absolute upstream `vp-vnp/`
path for [the batched builder](../scripts/build_lean_batched.py), regardless of
where the clones live.

## Attribution & License

`RemarkN6.lean` builds on `Statement.lean` and `Solution.lean` from [`anthropics/formal-math`](https://github.com/anthropics/formal-math) (licensed under Apache-2.0). All original files in this directory are likewise licensed under Apache-2.0.
