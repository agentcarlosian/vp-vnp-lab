import Specs.IrOpt.Statement
import Solution.Lem_simpAdd_sound
import Solution.Lem_simpMul_sound
import Solution.Lem_simpSub_sound

namespace PCVHProofs
open IrOpt

theorem optPass_sound (env : Nat → Int) (e : Expr) : eval env (optPass e) = eval env e := by
  induction e
  all_goals (try simp [eval, optPass, PCVHProofs.simpAdd_sound, PCVHProofs.simpMul_sound, PCVHProofs.simpSub_sound, *])
  all_goals (try omega)
  all_goals (try grind)

end PCVHProofs
