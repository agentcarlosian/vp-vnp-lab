import Solution
import RemarkN6

universe u

/-- **Unconditional Lean 4 kernel formalization of Remark N.6:**
    Over every field of characteristic ≠ 2, `perm F m` has superpolynomial border
    determinantal complexity `> m ^ (c * (log₂ m) ^ (1 / 3))`, proved unconditionally
    by composing our Samuelson-Berkowitz formalization `RemarkN6` with `Solution.mainTheoremApprox`. -/
theorem remarkN6_unconditional :
    ∃ c : ℝ, 0 < c ∧ ∀ p : ℕ, p ≠ 2 → ∃ m₀ : ℕ,
      ∀ (F : Type u) [Field F] [CharP F p], ∀ m ≥ m₀, ∀ k : ℕ,
        RemarkN6.BorderDetApprox (Statement.perm F m) k → Statement.Beyond c m k :=
  RemarkN6.remarkN6_of_mainTheoremApprox Solution.mainTheoremApprox

#print axioms Solution.mainTheorem
#print axioms Solution.separation
#print axioms Solution.mainTheoremApprox
#print axioms Solution.separationClosure
#print axioms Solution.permanent_over_real
#print axioms remarkN6_unconditional
