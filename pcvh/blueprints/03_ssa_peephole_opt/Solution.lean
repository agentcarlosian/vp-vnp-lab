import Specs.IrOpt.Statement
import Solution.Lem_iropt_spec_nonvacuous
import Solution.Lem_simpAdd_sound
import Solution.Lem_simpMul_sound
import Solution.Lem_simpSub_sound
import Solution.Lem_optPass_nonexpanding
import Solution.Lem_optPass_sound

/- Auto-assembled by PCVH Stage 3/4 Orchestrator. Verified by Zone C Palomar Gate. -/

namespace Solution
open IrOpt

theorem iropt_spec_nonvacuous : let x := Expr.var 0
    let sample := Expr.sub (Expr.add (Expr.mul x (Expr.const 1)) (Expr.const 0)) (Expr.add x (Expr.sub (Expr.const 2) (Expr.const 2)))
    optPass sample = Expr.const 0 ∧ exprSize (optPass sample) < exprSize sample :=
  PCVHProofs.iropt_spec_nonvacuous

theorem simpAdd_sound (env : Nat → Int) (a : Expr) (b : Expr) : eval env (simpAdd a b) = eval env a + eval env b :=
  PCVHProofs.simpAdd_sound env a b

theorem simpMul_sound (env : Nat → Int) (a : Expr) (b : Expr) : eval env (simpMul a b) = eval env a * eval env b :=
  PCVHProofs.simpMul_sound env a b

theorem simpSub_sound (env : Nat → Int) (a : Expr) (b : Expr) : eval env (simpSub a b) = eval env a - eval env b :=
  PCVHProofs.simpSub_sound env a b

theorem optPass_nonexpanding (e : Expr) : exprSize (optPass e) ≤ exprSize e :=
  PCVHProofs.optPass_nonexpanding e

theorem optPass_sound (env : Nat → Int) (e : Expr) : eval env (optPass e) = eval env e :=
  PCVHProofs.optPass_sound env e

end Solution
