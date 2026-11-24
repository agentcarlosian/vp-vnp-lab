/-
  Blueprint 5 — Human-Audited TCB Specification (`Statement.lean`)
  Proof-Carrying Theorem C.1 CAT(0) Quantum-Network Entanglement Capacity Bounds
  (Bridges CVXPY SOCP dual certificates from `quantum-cat0-checker` into Lean 4.)
-/

namespace Cat0Cert

/-- Integer-scaled squared distance matrix `u i j = d(i, j)^2` on `n` parties. -/
abbrev SqMetric (n : Nat) := Fin n → Fin n → Int

/-- Theorem C.1 / Lemma C.4(b) Enflo roundness-2 inequality on 4-cycle `(a - b - c - d - a)`:
    `d(a,c)^2 + d(b,d)^2 ≤ d(a,b)^2 + d(b,c)^2 + d(c,d)^2 + d(d,a)^2`. -/
def EnfloCycle {n : Nat} (u : SqMetric n) (a b c d : Fin n) : Prop :=
  u a c + u b d ≤ u a b + u b c + u c d + u d a

/-- Sum of squared edge lengths around the 4-cycle `C_4`. -/
def c4SideSum (u : SqMetric 4) : Int :=
  u 0 1 + u 1 2 + u 2 3 + u 3 0

/-- Sum of squared edge lengths across all 12 edges of the 3D quantum repeater cube `Q_3`. -/
def q3EdgeSum (u : SqMetric 8) : Int :=
  -- 4 bottom face edges (0-1-3-2-0)
  u 0 1 + u 1 3 + u 3 2 + u 2 0 +
  -- 4 top face edges (4-5-7-6-4)
  u 4 5 + u 5 7 + u 7 6 + u 6 4 +
  -- 4 vertical edges
  u 3 7 + u 4 0 + u 2 6 + u 5 1

/-- Sum of squared lengths of the 4 antipodal body diagonals of `Q_3`. -/
def q3BodyDiagSum (u : SqMetric 8) : Int :=
  u 0 7 + u 1 6 + u 2 5 + u 3 4

/-- Theorem C.1 CAT(0) hypotheses on the 4-quadrilateral decomposition of `Q_3`:
    bottom face, top face, and the 2 orthogonal diagonal rectangles. -/
def Q3Cat0 (u : SqMetric 8) : Prop :=
  EnfloCycle u 0 1 3 2 ∧
  EnfloCycle u 4 5 7 6 ∧
  EnfloCycle u 0 3 7 4 ∧
  EnfloCycle u 1 2 6 5

/-- Euclidean unit square `SqMetric 4` (sides = 1, diagonals = 2). -/
def unitSquareSq : SqMetric 4 := fun i j =>
  if i == j then 0
  else if (i.val + j.val) % 2 == 0 then 2
  else 1

/-- Euclidean unit 3D cube `SqMetric 8` (`u(v, w) = popcount(v ^^^ w)`). -/
def unitCubeSq : SqMetric 8 := fun i j =>
  let x := i.val ^^^ j.val
  Int.ofNat ((x &&& 1) + ((x >>> 1) &&& 1) + ((x >>> 2) &&& 1))

end Cat0Cert
