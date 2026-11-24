import Specs.IrOpt.Statement

namespace PCVHProofs
open IrOpt

theorem iropt_spec_nonvacuous : let x := Expr.var 0
    let sample := Expr.sub (Expr.add (Expr.mul x (Expr.const 1)) (Expr.const 0)) (Expr.add x (Expr.sub (Expr.const 2) (Expr.const 2)))
    optPass sample = Expr.const 0 ∧ exprSize (optPass sample) < exprSize sample := by
  decide

end PCVHProofs
