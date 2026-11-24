import Specs.IrOpt.Statement

/-
  Blueprint 3 — Target Compiler Soundness Theorems (`Challenge.lean`)
  Solved autonomously from scratch by `pcvh prove` (no hand-written Solution.lean!).
-/

namespace Challenge
open IrOpt

/-- 1. Local rewrite soundness for `simpAdd`. -/
theorem simpAdd_sound (env : Nat → Int) (a b : Expr) :
    eval env (simpAdd a b) = eval env a + eval env b := by
  sorry

/-- 2. Local rewrite soundness for `simpSub`. -/
theorem simpSub_sound (env : Nat → Int) (a b : Expr) :
    eval env (simpSub a b) = eval env a - eval env b := by
  sorry

/-- 3. Local rewrite soundness for `simpMul`. -/
theorem simpMul_sound (env : Nat → Int) (a b : Expr) :
    eval env (simpMul a b) = eval env a * eval env b := by
  sorry

/-- 4. Full bottom-up compiler pass soundness: preserves exact semantics for all ASTs & environments. -/
theorem optPass_sound (env : Nat → Int) (e : Expr) :
    eval env (optPass e) = eval env e := by
  sorry

/-- 5. Code-size non-expansion: `optPass` never increases AST node count. -/
theorem optPass_nonexpanding (e : Expr) :
    exprSize (optPass e) ≤ exprSize e := by
  sorry

/-- 6. Mandatory non-vacuity witness: concrete AST `(x * 1 + 0) - (x + (2 - 2))` folds strictly to `const 0`. -/
theorem iropt_spec_nonvacuous :
    let x := Expr.var 0
    let sample := Expr.sub (Expr.add (Expr.mul x (Expr.const 1)) (Expr.const 0)) (Expr.add x (Expr.sub (Expr.const 2) (Expr.const 2)))
    optPass sample = Expr.const 0 ∧ exprSize (optPass sample) < exprSize sample := by
  sorry

end Challenge
