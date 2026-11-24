import Specs.Vault.Statement

/-
  Blueprint 1 — Verified DeFi Proof Package (`Solution.lean`)
  Zero `sorry`, zero Mathlib, constructive standard axioms only.
-/

namespace Solution
open DeFi

theorem amm_swap_preserves_k_monotonicity (x y dx : Nat) (hx : 0 < x) :
    poolK { reserveX := x, reserveY := y } ≤ poolK (ammSwapXForY { reserveX := x, reserveY := y } dx).1 := by
  simp only [poolK, ammSwapXForY, ammAmountOut]
  have hdiv : (y * dx) / (x + dx) * (x + dx) ≤ y * dx := Nat.div_mul_le_self (y * dx) (x + dx)
  have hcomm : (x + dx) * ((y * dx) / (x + dx)) ≤ y * dx := by
    rw [Nat.mul_comm]
    exact hdiv
  have hdist : (x + dx) * (y - (y * dx) / (x + dx)) = (x + dx) * y - (x + dx) * ((y * dx) / (x + dx)) :=
    Nat.mul_sub_left_distrib (x + dx) y ((y * dx) / (x + dx))
  have hexp : (x + dx) * y = x * y + y * dx := by
    rw [Nat.add_mul, Nat.mul_comm dx y]
  rw [hdist, hexp]
  omega

theorem amm_swap_never_drains_reserve (x y dx : Nat) (hx : 0 < x) (hy : 0 < y) :
    0 < (ammSwapXForY { reserveX := x, reserveY := y } dx).1.reserveY := by
  simp only [ammSwapXForY, ammAmountOut]
  have hpos : 0 < x * y := Nat.mul_pos hx hy
  have hlt : y * dx < (x + dx) * y := by
    rw [Nat.add_mul, Nat.mul_comm dx y]
    omega
  have hdivlt : (y * dx) / (x + dx) < y := Nat.div_lt_of_lt_mul hlt
  omega

theorem vault_deposit_preserves_share_price_floor
    (A S dA : Nat) (hA : 0 < A) (hS : 0 < S) :
    A * (vaultDeposit { totalAssets := A, totalShares := S } dA).1.totalShares ≤
    (vaultDeposit { totalAssets := A, totalShares := S } dA).1.totalAssets * S := by
  simp only [vaultDeposit, previewDeposit]
  have hA0 : (A == 0) = false := by
    cases A with
    | zero => omega
    | succ _ => rfl
  have hS0 : (S == 0) = false := by
    cases S with
    | zero => omega
    | succ _ => rfl
  simp only [hA0, hS0, Bool.or_false, Bool.false_eq_true, ↓reduceIte]
  have hdiv : (dA * S) / A * A ≤ dA * S := Nat.div_mul_le_self (dA * S) A
  have h1 : A * (S + (dA * S) / A) = A * S + (dA * S) / A * A := by
    rw [Nat.mul_add, Nat.mul_comm A ((dA * S) / A)]
  have h2 : (A + dA) * S = A * S + dA * S := Nat.add_mul A dA S
  rw [h1, h2]
  omega

theorem vault_redeem_never_exceeds_assets
    (A S sh : Nat) (hS : 0 < S) (hle : sh ≤ S) :
    previewRedeem { totalAssets := A, totalShares := S } sh ≤ A := by
  simp only [previewRedeem]
  have hS0 : (S == 0) = false := by
    cases S with
    | zero => omega
    | succ _ => rfl
  simp only [hS0, Bool.false_eq_true, ↓reduceIte]
  have hmul : sh * A ≤ S * A := Nat.mul_le_mul_right A hle
  have hdiv : (sh * A) / S ≤ (S * A) / S := Nat.div_le_div_right hmul
  rw [Nat.mul_div_cancel_left A hS] at hdiv
  exact hdiv

theorem vault_deposit_redeem_no_free_money
    (A S dA : Nat) (hA : 0 < A) (hS : 0 < S) :
    let res := vaultDeposit { totalAssets := A, totalShares := S } dA
    previewRedeem res.1 res.2 ≤ dA := by
  dsimp only
  simp only [vaultDeposit, previewDeposit, previewRedeem]
  have hA0 : (A == 0) = false := by
    cases A with
    | zero => omega
    | succ _ => rfl
  have hS0 : (S == 0) = false := by
    cases S with
    | zero => omega
    | succ _ => rfl
  simp only [hA0, hS0, Bool.or_false, Bool.false_eq_true, ↓reduceIte]
  have hSpos : 0 < S + (dA * S) / A := Nat.add_pos_left hS ((dA * S) / A)
  have hSsum0 : (S + (dA * S) / A == 0) = false := by
    cases h : S + (dA * S) / A with
    | zero => rw [h] at hSpos; cases hSpos
    | succ _ => rfl
  simp only [hSsum0, Bool.false_eq_true, ↓reduceIte]
  have hdiv : (dA * S) / A * A ≤ dA * S := Nat.div_mul_le_self (dA * S) A
  have hbound : (dA * S) / A * (A + dA) ≤ (S + (dA * S) / A) * dA := by
    have h1 : (dA * S) / A * (A + dA) = (dA * S) / A * A + (dA * S) / A * dA :=
      Nat.mul_add ((dA * S) / A) A dA
    have h2 : (S + (dA * S) / A) * dA = dA * S + (dA * S) / A * dA := by
      rw [Nat.add_mul, Nat.mul_comm S dA]
    rw [h1, h2]
    omega
  exact Nat.div_le_of_le_mul hbound

theorem vault_spec_nonvacuous :
    let p0 : PoolState := { reserveX := 1000, reserveY := 2000 }
    let (p1, dy) := ammSwapXForY p0 250
    let v0 : VaultState := { totalAssets := 1000, totalShares := 1000 }
    let (v1, minted) := vaultDeposit v0 333
    let (_, out) := vaultRedeem v1 minted
    dy = 400 ∧ poolK p0 ≤ poolK p1 ∧ minted = 333 ∧ out ≤ 333 := by
  decide

end Solution
