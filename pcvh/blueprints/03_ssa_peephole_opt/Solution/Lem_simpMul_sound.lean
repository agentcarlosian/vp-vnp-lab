import Specs.IrOpt.Statement

namespace PCVHProofs
open IrOpt

theorem simpMul_sound (env : Nat → Int) (a : Expr) (b : Expr) : eval env (simpMul a b) = eval env a * eval env b := by
  simp only [eval, exprSize, simpAdd, simpSub, simpMul, optPass]
  all_goals (try split)
  all_goals (try simp_all [eval, exprSize, simpAdd, simpSub, simpMul, optPass])
  all_goals (try split)
  all_goals (try simp_all [eval, exprSize, simpAdd, simpSub, simpMul, optPass])
  all_goals (try omega)
  all_goals (try grind)

end PCVHProofs
