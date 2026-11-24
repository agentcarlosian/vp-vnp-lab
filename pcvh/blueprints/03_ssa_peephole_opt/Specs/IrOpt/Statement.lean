/-
  Blueprint 3 — Human-Audited TCB Specification (`Statement.lean`)
  Arithmetic IR Peephole Optimizer & Constant Folder
  (Intentionally ships with NO hand-written Solution.lean — solved autonomously by `pcvh prove`!)
-/

namespace IrOpt

/-- Simple expression IR (constants, register variables, add, sub, mul). -/
inductive Expr where
  | const (v : Int)
  | var (reg : Nat)
  | add (a b : Expr)
  | sub (a b : Expr)
  | mul (a b : Expr)
  deriving Repr, DecidableEq

/-- Denotational semantics under register environment `env : Nat → Int`. -/
def eval (env : Nat → Int) : Expr → Int
  | Expr.const v => v
  | Expr.var r => env r
  | Expr.add a b => eval env a + eval env b
  | Expr.sub a b => eval env a - eval env b
  | Expr.mul a b => eval env a * eval env b

/-- AST node count (measures code size / non-expansion). -/
def exprSize : Expr → Nat
  | Expr.const _ => 1
  | Expr.var _ => 1
  | Expr.add a b => 1 + exprSize a + exprSize b
  | Expr.sub a b => 1 + exprSize a + exprSize b
  | Expr.mul a b => 1 + exprSize a + exprSize b

/-- Single-node algebraic peephole + constant-folding smart constructors. -/
def simpAdd : Expr → Expr → Expr
  | Expr.const x, Expr.const y => Expr.const (x + y)
  | Expr.const 0, b => b
  | a, Expr.const 0 => a
  | a, b => Expr.add a b

def simpSub : Expr → Expr → Expr
  | Expr.const x, Expr.const y => Expr.const (x - y)
  | a, Expr.const 0 => a
  | a, b => if a == b then Expr.const 0 else Expr.sub a b

def simpMul : Expr → Expr → Expr
  | Expr.const x, Expr.const y => Expr.const (x * y)
  | Expr.const 0, _ => Expr.const 0
  | _, Expr.const 0 => Expr.const 0
  | Expr.const 1, b => b
  | a, Expr.const 1 => a
  | a, b => Expr.mul a b

/-- Bottom-up constant folding + algebraic peephole optimization pass. -/
def optPass : Expr → Expr
  | Expr.const v => Expr.const v
  | Expr.var r => Expr.var r
  | Expr.add a b => simpAdd (optPass a) (optPass b)
  | Expr.sub a b => simpSub (optPass a) (optPass b)
  | Expr.mul a b => simpMul (optPass a) (optPass b)

end IrOpt
