import Specs.Cat0.Statement

/-
  AUTO-SYNTHESIZED BY `pcvh.cat0_bridge` FROM `quantum-cat0-checker` CVXPY SOCP DUALITY
  - Certified C_4 CAT(0) ratio: rho = 1  (exact sqrt(2)x compression over triangle bound)
  - Certified Q_3 CAT(0) ratio: rho = 1  (exact sqrt(3)x compression over triangle bound)
  Zero `sorry`, zero custom axioms, zero Mathlib dependency.
-/

namespace Solution
open Cat0Cert

private theorem int_sq_nonneg (x : Int) : 0 ≤ x * x := by
  by_cases h : 0 ≤ x
  · exact Int.mul_nonneg h h
  · have hneg : 0 ≤ -x := by omega
    have hmul : 0 ≤ (-x) * (-x) := Int.mul_nonneg hneg hneg
    have heq : (-x) * (-x) = x * x := Int.neg_mul_neg x x
    omega

private theorem cs2_int (a b : Int) :
    (a + b) * (a + b) ≤ 2 * (a * a + b * b) := by
  have hsq : 0 ≤ (a - b) * (a - b) := int_sq_nonneg (a - b)
  have hid : (a - b) * (a - b) = 2 * (a * a + b * b) - (a + b) * (a + b) := by
    have h1 : (a - b) * (a - b) = a * a - a * b - b * a + b * b := by
      rw [Int.sub_mul, Int.mul_sub, Int.mul_sub]
      omega
    have h2 : (a + b) * (a + b) = a * a + a * b + b * a + b * b := by
      rw [Int.add_mul, Int.mul_add, Int.mul_add]
      omega
    have hc : b * a = a * b := Int.mul_comm b a
    omega
  omega

private theorem cs4_int (a b c d : Int) :
    (a + b + c + d) * (a + b + c + d) ≤ 4 * (a * a + b * b + c * c + d * d) := by
  have h1 := cs2_int (a + b) (c + d)
  have h2 := cs2_int a b
  have h3 := cs2_int c d
  have hassoc : a + b + c + d = (a + b) + (c + d) := by omega
  rw [hassoc]
  omega

theorem c4_crossing_cat0_bound
    (u : SqMetric 4) (d02 d13 : Int)
    (h_cat0 : EnfloCycle u 0 1 2 3)
    (h02 : d02 * d02 = u 0 2)
    (h13 : d13 * d13 = u 1 3) :
    (d02 + d13) * (d02 + d13) ≤ 2 * c4SideSum u := by
  have hcs := cs2_int d02 d13
  unfold EnfloCycle at h_cat0
  unfold c4SideSum
  omega

theorem q3_cube_enflo_squared_bound
    (u : SqMetric 8) (h_symm : ∀ a b, u a b = u b a) (h_cat0 : Q3Cat0 u) :
    q3BodyDiagSum u ≤ q3EdgeSum u := by
  rcases h_cat0 with ⟨hBot, hTop, hDiag1, hDiag2⟩
  unfold EnfloCycle at hBot hTop hDiag1 hDiag2
  unfold q3BodyDiagSum q3EdgeSum
  have hs1 : u 7 4 = u 4 7 := h_symm 7 4
  have hs2 : u 6 5 = u 5 6 := h_symm 6 5
  have hs3 : u 1 2 = u 2 1 := h_symm 1 2
  -- Exact sum of the 4 CVXPY-certified CAT(0) quadrilateral inequalities (dual multipliers = [1, 1, 1, 1]):
  --   hBot + hTop + hDiag1 + hDiag2 cancels all 4 face diagonals identically!
  omega

theorem q3_cube_crossing_linear_bound
    (u : SqMetric 8) (b0 b1 b2 b3 : Int)
    (h_symm : ∀ a b, u a b = u b a)
    (h_cat0 : Q3Cat0 u)
    (hb0 : b0 * b0 = u 0 7) (hb1 : b1 * b1 = u 1 6)
    (hb2 : b2 * b2 = u 2 5) (hb3 : b3 * b3 = u 3 4) :
    (b0 + b1 + b2 + b3) * (b0 + b1 + b2 + b3) ≤ 4 * q3EdgeSum u := by
  have hcs := cs4_int b0 b1 b2 b3
  have henflo := q3_cube_enflo_squared_bound u h_symm h_cat0
  unfold q3BodyDiagSum at henflo
  omega

theorem cat0_spec_nonvacuous :
    EnfloCycle unitSquareSq 0 1 2 3 ∧
    unitSquareSq 0 2 + unitSquareSq 1 3 = c4SideSum unitSquareSq ∧
    Q3Cat0 unitCubeSq ∧
    q3BodyDiagSum unitCubeSq = q3EdgeSum unitCubeSq := by
  refine ⟨?_, rfl, ⟨?_, ?_, ?_, ?_⟩, rfl⟩
  · unfold EnfloCycle unitSquareSq; decide
  · unfold EnfloCycle unitCubeSq; decide
  · unfold EnfloCycle unitCubeSq; decide
  · unfold EnfloCycle unitCubeSq; decide
  · unfold EnfloCycle unitCubeSq; decide

end Solution
