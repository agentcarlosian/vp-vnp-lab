import Specs.IrOpt.Statement
import Solution.Lem_simpAdd_sound
import Solution.Lem_simpMul_sound
import Solution.Lem_simpSub_sound

namespace PCVHProofs
open IrOpt

theorem optPass_nonexpanding (e : Expr) : exprSize (optPass e) ≤ exprSize e := by
  induction e
  all_goals (try simp only [eval, exprSize, simpAdd, simpSub, simpMul, optPass, PCVHProofs.simpAdd_sound, PCVHProofs.simpMul_sound, PCVHProofs.simpSub_sound])
  all_goals (try split)
  all_goals (try simp_all [eval, exprSize, simpAdd, simpSub, simpMul, optPass])
  all_goals (try split)
  all_goals (try simp_all [eval, exprSize, simpAdd, simpSub, simpMul, optPass])
  all_goals (try omega)
  all_goals (try grind)

end PCVHProofs
