/-
Formalization of Remark N.6 ("determinantal complexity") from
"VP != VNP Over Every Field", closing the one numbered statement
not formalized in the original Lean development.

Proves via Samuelson-Berkowitz's division-free polynomial-size determinant
circuit (over any commutative ring, using PowerSeries + block triangularization)
and `Solution.mainTheoremApprox` that over every field of characteristic != 2,
the permanent `perm F m` is not approximated (in the formal Laurent series sense
of Definition N.1 / `Statement.Approximates`) by determinants of affine matrices
of size `m ^ (c * (log₂ m) ^ (1 / 3))`.
-/
import Mathlib
import Statement

open MvPolynomial Matrix Finset

universe u

namespace RemarkN6

/-! ### 1. Multi-output arithmetic circuits (`Circ`) -/

/-- A concrete arithmetic circuit (straight-line program) over a commutative semiring `R`
in variables `V`, stored as a list of polynomials where each gate is a variable, constant,
or sum/product of two earlier gates. -/
structure Circ (R : Type u) (V : Type) [CommSemiring R] where
  gates : List (MvPolynomial V R)
  valid : ∀ (k : ℕ) (hk : k < gates.length),
    (∃ v : V, gates[k] = X v) ∨
    (∃ a : R, gates[k] = MvPolynomial.C a) ∨
    (∃ i, ∃ hi : i < k, ∃ j, ∃ hj : j < k, gates[k] = gates[i]'(hi.trans hk) + gates[j]'(hj.trans hk)) ∨
    (∃ i, ∃ hi : i < k, ∃ j, ∃ hj : j < k, gates[k] = gates[i]'(hi.trans hk) * gates[j]'(hj.trans hk))

namespace Circ

variable {R : Type u} {V : Type} [CommSemiring R]

/-- The empty circuit. -/
def empty : Circ R V := ⟨[], fun _ hk => absurd hk (Nat.not_lt_zero _)⟩

/-- If `f` appears in `C.gates`, then `Statement.Computes f C.gates.length`. -/
theorem toComputes (C : Circ R V) {f : MvPolynomial V R} (hf : f ∈ C.gates) :
    Statement.Computes f C.gates.length := by
  classical
  refine ⟨fun k => C.gates.getD k 0, fun k hk => ?_, ?_⟩
  · have hget : ∀ m (hm : m < C.gates.length), C.gates.getD m 0 = C.gates[m] := by
      intro m hm
      simp [List.getD_eq_getElem?_getD, List.getElem?_eq_getElem hm]
    dsimp only
    rw [hget k hk]
    rcases C.valid k hk with h | h | ⟨i, hi, j, hj, h⟩ | ⟨i, hi, j, hj, h⟩
    · exact Or.inl h
    · exact Or.inr (Or.inl h)
    · exact Or.inr (Or.inr (Or.inl ⟨i, hi, j, hj, by rw [hget i (hi.trans hk), hget j (hj.trans hk)]; exact h⟩))
    · exact Or.inr (Or.inr (Or.inr ⟨i, hi, j, hj, by rw [hget i (hi.trans hk), hget j (hj.trans hk)]; exact h⟩))
  · obtain ⟨k, hk, rfl⟩ := List.mem_iff_getElem.1 hf
    exact ⟨k, hk, by simp [List.getD_eq_getElem?_getD, List.getElem?_eq_getElem hk]⟩

/-- Append one valid gate to a circuit. -/
def snoc (C : Circ R V) (g : MvPolynomial V R)
    (hg : (∃ v : V, g = X v) ∨ (∃ a : R, g = MvPolynomial.C a) ∨
      (∃ i, ∃ hi : i < C.gates.length, ∃ j, ∃ hj : j < C.gates.length, g = C.gates[i]'hi + C.gates[j]'hj) ∨
      (∃ i, ∃ hi : i < C.gates.length, ∃ j, ∃ hj : j < C.gates.length, g = C.gates[i]'hi * C.gates[j]'hj)) : Circ R V where
  gates := C.gates ++ [g]
  valid := by
    intro k hk
    rw [List.length_append, List.length_singleton] at hk
    by_cases hlt : k < C.gates.length
    · rw [List.getElem_append_left hlt]
      rcases C.valid k hlt with h | h | ⟨i, hi, j, hj, h⟩ | ⟨i, hi, j, hj, h⟩
      · exact Or.inl h
      · exact Or.inr (Or.inl h)
      · exact Or.inr (Or.inr (Or.inl ⟨i, hi, j, hj, by
          rw [List.getElem_append_left (hi.trans hlt), List.getElem_append_left (hj.trans hlt)]; exact h⟩))
      · exact Or.inr (Or.inr (Or.inr ⟨i, hi, j, hj, by
          rw [List.getElem_append_left (hi.trans hlt), List.getElem_append_left (hj.trans hlt)]; exact h⟩))
    · have hk_eq : k = C.gates.length := by omega
      subst hk_eq
      simp only [List.getElem_append_right (le_refl _), Nat.sub_self, List.getElem_cons_zero]
      rcases hg with h | h | ⟨i, hi, j, hj, h⟩ | ⟨i, hi, j, hj, h⟩
      · exact Or.inl h
      · exact Or.inr (Or.inl h)
      · exact Or.inr (Or.inr (Or.inl ⟨i, hi, j, hj, by
          rw [List.getElem_append_left hi, List.getElem_append_left hj]; exact h⟩))
      · exact Or.inr (Or.inr (Or.inr ⟨i, hi, j, hj, by
          rw [List.getElem_append_left hi, List.getElem_append_left hj]; exact h⟩))

/-- `C'` extends `C` if every polynomial computed by `C` is computed by `C'`. -/
def Extends (C C' : Circ R V) : Prop := ∀ p ∈ C.gates, p ∈ C'.gates

theorem Extends.refl (C : Circ R V) : Extends C C := fun _ h => h
theorem Extends.trans {C₁ C₂ C₃ : Circ R V} (h₁ : Extends C₁ C₂) (h₂ : Extends C₂ C₃) :
    Extends C₁ C₃ := fun _ h => h₂ _ (h₁ _ h)

theorem exists_addX (C : Circ R V) (v : V) :
    ∃ C' : Circ R V, Extends C C' ∧ X v ∈ C'.gates ∧ C'.gates.length = C.gates.length + 1 :=
  ⟨C.snoc (X v) (Or.inl ⟨v, rfl⟩), fun _ hp => List.mem_append_left _ hp,
    by simp [snoc], by simp [snoc]⟩

theorem exists_addC (C : Circ R V) (a : R) :
    ∃ C' : Circ R V, Extends C C' ∧ MvPolynomial.C a ∈ C'.gates ∧ C'.gates.length = C.gates.length + 1 :=
  ⟨C.snoc (MvPolynomial.C a) (Or.inr (Or.inl ⟨a, rfl⟩)), fun _ hp => List.mem_append_left _ hp,
    by simp [snoc], by simp [snoc]⟩

theorem exists_addAdd (C : Circ R V) {f g : MvPolynomial V R}
    (hf : f ∈ C.gates) (hg : g ∈ C.gates) :
    ∃ C' : Circ R V, Extends C C' ∧ f + g ∈ C'.gates ∧ C'.gates.length = C.gates.length + 1 := by
  obtain ⟨i, hi, rfl⟩ := List.mem_iff_getElem.1 hf
  obtain ⟨j, hj, rfl⟩ := List.mem_iff_getElem.1 hg
  exact ⟨C.snoc (C.gates[i] + C.gates[j]) (Or.inr (Or.inr (Or.inl ⟨i, hi, j, hj, rfl⟩))),
    fun _ hp => List.mem_append_left _ hp, by simp [snoc], by simp [snoc]⟩

theorem exists_addMul (C : Circ R V) {f g : MvPolynomial V R}
    (hf : f ∈ C.gates) (hg : g ∈ C.gates) :
    ∃ C' : Circ R V, Extends C C' ∧ f * g ∈ C'.gates ∧ C'.gates.length = C.gates.length + 1 := by
  obtain ⟨i, hi, rfl⟩ := List.mem_iff_getElem.1 hf
  obtain ⟨j, hj, rfl⟩ := List.mem_iff_getElem.1 hg
  exact ⟨C.snoc (C.gates[i] * C.gates[j]) (Or.inr (Or.inr (Or.inr ⟨i, hi, j, hj, rfl⟩))),
    fun _ hp => List.mem_append_left _ hp, by simp [snoc], by simp [snoc]⟩

theorem exists_addNeg {R : Type u} [CommRing R] (C : Circ R V) {f : MvPolynomial V R}
    (hf : f ∈ C.gates) :
    ∃ C' : Circ R V, Extends C C' ∧ -f ∈ C'.gates ∧ C'.gates.length ≤ C.gates.length + 2 := by
  obtain ⟨C₁, h₁, hc, hl₁⟩ := exists_addC C (-1 : R)
  obtain ⟨C₂, h₂, hm, hl₂⟩ := exists_addMul C₁ hc (h₁ _ hf)
  refine ⟨C₂, h₁.trans h₂, ?_, by omega⟩
  simpa using hm

/-- Compute the sum of a list of polynomials already in `C` using at most `l.length + 1` extra gates. -/
theorem exists_listSum (C : Circ R V) (l : List (MvPolynomial V R)) (hl : ∀ p ∈ l, p ∈ C.gates) :
    ∃ C' : Circ R V, Extends C C' ∧ l.sum ∈ C'.gates ∧ C'.gates.length ≤ C.gates.length + l.length + 1 := by
  induction l generalizing C with
  | nil =>
    obtain ⟨C₁, h₁, h0, hl₁⟩ := exists_addC C 0
    exact ⟨C₁, h₁, by simpa using h0, by omega⟩
  | cons a t ih =>
    obtain ⟨C₁, h₁, ht, hl₁⟩ := ih C (fun p hp => hl p (List.mem_cons_of_mem a hp))
    obtain ⟨C₂, h₂, ha, hl₂⟩ := exists_addAdd C₁ (h₁ _ (hl a List.mem_cons_self)) ht
    exact ⟨C₂, h₁.trans h₂, by simpa using ha, by simp; omega⟩

/-- Compute a dot product `∑ i : Fin n, u i * v i` using at most `2 * n + 1` extra gates. -/
theorem exists_dotProduct (C : Circ R V) {n : ℕ} (u v : Fin n → MvPolynomial V R)
    (hu : ∀ i, u i ∈ C.gates) (hv : ∀ i, v i ∈ C.gates) :
    ∃ C' : Circ R V, Extends C C' ∧ (∑ i : Fin n, u i * v i) ∈ C'.gates ∧
      C'.gates.length ≤ C.gates.length + 2 * n + 1 := by
  -- First compute all `n` products `u i * v i`, then sum them.
  suffices h : ∀ k (hk : k ≤ n),
      ∃ C' : Circ R V, Extends C C' ∧
        (∑ i : Fin k, u ⟨i.1, by omega⟩ * v ⟨i.1, by omega⟩) ∈ C'.gates ∧
        C'.gates.length ≤ C.gates.length + 2 * k + 1 by
    obtain ⟨C', hE, hm, hl⟩ := h n le_rfl
    exact ⟨C', hE, hm, hl⟩
  intro k hk
  induction k with
  | zero =>
    obtain ⟨C₁, h₁, h0, hl₁⟩ := exists_addC C 0
    exact ⟨C₁, h₁, by simpa using h0, by omega⟩
  | succ k ih =>
    obtain ⟨C₁, h₁, hsum, hl₁⟩ := ih (by omega)
    obtain ⟨C₂, h₂, hprod, hl₂⟩ := exists_addMul C₁ (h₁ _ (hu ⟨k, by omega⟩)) (h₁ _ (hv ⟨k, by omega⟩))
    obtain ⟨C₃, h₃, hadd, hl₃⟩ := exists_addAdd C₂ (h₂ _ hsum) hprod
    refine ⟨C₃, (h₁.trans h₂).trans h₃, ?_, by omega⟩
    rw [Fin.sum_univ_castSucc]
    exact hadd

/-- Compute a single affine polynomial (`f.totalDegree ≤ 1`) over finite `V`
in at most `4 * Fintype.card V + 2` extra gates. -/
theorem exists_affine [Fintype V] (C : Circ R V) (f : MvPolynomial V R) (hf : f.totalDegree ≤ 1) :
    ∃ C' : Circ R V, Extends C C' ∧ f ∈ C'.gates ∧
      C'.gates.length ≤ C.gates.length + 4 * Fintype.card V + 2 := by
  classical
  -- Decompose `f = C (coeff 0 f) + ∑ v, C (coeff (single v 1) f) * X v`.
  have hdecomp : f = MvPolynomial.C (coeff 0 f) +
      ∑ v : V, MvPolynomial.C (coeff (Finsupp.single v 1) f) * X v := by
    ext d
    simp only [coeff_add, coeff_C, coeff_sum, coeff_C_mul, coeff_X]
    by_cases hd0 : d = 0
    · subst hd0
      simp
    · simp only [if_neg (Ne.symm hd0), zero_add]
      by_cases hle : d.sum (fun _ k => k) ≤ 1
      · -- Since `d ≠ 0` and `sum d ≤ 1`, `d = single v 1` for a unique `v`.
        have hsupp : d.support.Nonempty := Finsupp.support_nonempty_iff.2 hd0
        obtain ⟨v, hv⟩ := hsupp
        have hv1 : 1 ≤ d v := Nat.pos_of_ne_zero (Finsupp.mem_support_iff.1 hv)
        have hle_sum : d v ≤ d.sum (fun _ k => k) :=
          Finset.single_le_sum (f := fun x => d x) (fun _ _ => Nat.zero_le _) hv
        have hdv : d v = 1 := by omega
        have hd_eq : d = Finsupp.single v 1 := by
          ext w
          by_cases hvw : w = v
          · subst hvw; simp [hdv]
          · rw [Finsupp.single_eq_of_ne hvw]
            by_contra hdw
            have hw : w ∈ d.support := Finsupp.mem_support_iff.2 hdw
            have h2 : d v + d w ≤ d.sum (fun _ k => k) := by
              have hpair : ({v, w} : Finset V) ⊆ d.support := by
                intro x hx
                simp only [Finset.mem_insert, Finset.mem_singleton] at hx
                rcases hx with rfl | rfl <;> assumption
              calc d v + d w = ∑ x ∈ ({v, w} : Finset V), d x := by
                    rw [Finset.sum_pair (Ne.symm hvw)]
                _ ≤ ∑ x ∈ d.support, d x :=
                    Finset.sum_le_sum_of_subset_of_nonneg hpair (fun _ _ _ => Nat.zero_le _)
            have : 1 ≤ d w := Nat.pos_of_ne_zero hdw
            omega
        subst hd_eq
        rw [Finset.sum_eq_single v]
        · simp
        · intro w _ hne
          have : Finsupp.single w 1 ≠ Finsupp.single v 1 := by
            intro heq
            have := congrArg (fun g : V →₀ ℕ => g w) heq
            simp [Finsupp.single_eq_of_ne hne] at this
          simp [this]
        · intro hv'; exact absurd (Finset.mem_univ v) hv'
      · have hc0 : coeff d f = 0 := by
          by_contra hne
          have hmem : d ∈ f.support := mem_support_iff.2 hne
          have hdeg : d.sum (fun _ k => k) ≤ f.totalDegree :=
            Finset.le_sup (f := fun s : V →₀ ℕ => s.sum fun _ k => k) hmem
          omega
        rw [hc0]
        symm
        apply Finset.sum_eq_zero
        intro v _
        have hne : Finsupp.single v 1 ≠ d := by
          rintro rfl
          apply hle
          simp [Finsupp.sum_single_index]
        simp [hne]
  -- Compute the constant term + each variable term in a loop over `Fin (Fintype.card V)`.
  let e : Fin (Fintype.card V) ≃ V := (Fintype.equivFin V).symm
  obtain ⟨C₀, h₀, hc0, hl₀⟩ := exists_addC C (coeff 0 f)
  suffices hloop : ∀ k (hk : k ≤ Fintype.card V),
      ∃ C' : Circ R V, Extends C₀ C' ∧
        (MvPolynomial.C (coeff 0 f) + ∑ i : Fin k,
          MvPolynomial.C (coeff (Finsupp.single (e ⟨i.1, by omega⟩) 1) f) * X (e ⟨i.1, by omega⟩)) ∈ C'.gates ∧
        C'.gates.length ≤ C₀.gates.length + 4 * k by
    obtain ⟨C', hE, hmem, hlen⟩ := hloop (Fintype.card V) le_rfl
    refine ⟨C', h₀.trans hE, ?_, by omega⟩
    rw [hdecomp]
    have hsum_eq : (∑ i : Fin (Fintype.card V),
        MvPolynomial.C (coeff (Finsupp.single (e i) 1) f) * X (e i)) =
        ∑ v : V, MvPolynomial.C (coeff (Finsupp.single v 1) f) * X v :=
      Equiv.sum_comp e (fun v => MvPolynomial.C (coeff (Finsupp.single v 1) f) * X v)
    rw [← hsum_eq]
    exact hmem
  intro k hk
  induction k with
  | zero => exact ⟨C₀, Extends.refl C₀, by simpa using hc0, by omega⟩
  | succ k ih =>
    obtain ⟨C₁, h₁, hprev, hl₁⟩ := ih (by omega)
    let v : V := e ⟨k, by omega⟩
    obtain ⟨C₂, h₂, hcv, hl₂⟩ := exists_addC C₁ (coeff (Finsupp.single v 1) f)
    obtain ⟨C₃, h₃, hxv, hl₃⟩ := exists_addX C₂ v
    obtain ⟨C₄, h₄, hprod, hl₄⟩ := exists_addMul C₃ (h₃ _ hcv) hxv
    obtain ⟨C₅, h₅, hadd, hl₅⟩ := exists_addAdd C₄ ((h₂.trans (h₃.trans h₄)) _ hprev) hprod
    refine ⟨C₅, h₁.trans (h₂.trans (h₃.trans (h₄.trans h₅))), ?_, by omega⟩
    rw [Fin.sum_univ_castSucc, ← add_assoc]
    exact hadd

/-- Compute all `k * k` entries of an affine `k × k` matrix `M` in at most
`k * k * (4 * Fintype.card V + 2)` extra gates. -/
theorem exists_affineMatrix [Fintype V] (C : Circ R V) {k : ℕ}
    (M : Matrix (Fin k) (Fin k) (MvPolynomial V R))
    (hM : ∀ i j, (M i j).totalDegree ≤ 1) :
    ∃ C' : Circ R V, Extends C C' ∧ (∀ i j, M i j ∈ C'.gates) ∧
      C'.gates.length ≤ C.gates.length + k * k * (4 * Fintype.card V + 2) := by
  let pairs : Fin (k * k) ≃ Fin k × Fin k := finProdFinEquiv.symm
  suffices h : ∀ t (ht : t ≤ k * k),
      ∃ C' : Circ R V, Extends C C' ∧
        (∀ idx : Fin t, M (pairs ⟨idx.1, by omega⟩).1 (pairs ⟨idx.1, by omega⟩).2 ∈ C'.gates) ∧
        C'.gates.length ≤ C.gates.length + t * (4 * Fintype.card V + 2) by
    obtain ⟨C', hE, hmem, hlen⟩ := h (k * k) le_rfl
    refine ⟨C', hE, fun i j => ?_, hlen⟩
    have := hmem (pairs.symm (i, j))
    simpa using this
  intro t ht
  induction t with
  | zero => exact ⟨C, Extends.refl C, fun idx => Fin.elim0 idx, by omega⟩
  | succ t ih =>
    obtain ⟨C₁, h₁, hprev, hl₁⟩ := ih (by omega)
    let p := pairs ⟨t, by omega⟩
    obtain ⟨C₂, h₂, hnew, hl₂⟩ := exists_affine C₁ (M p.1 p.2) (hM p.1 p.2)
    refine ⟨C₂, h₁.trans h₂, fun idx => ?_, by
      have : (t + 1) * (4 * Fintype.card V + 2) = t * (4 * Fintype.card V + 2) + (4 * Fintype.card V + 2) := by ring
      omega⟩
    by_cases hlt : idx.1 < t
    · exact h₂ _ (hprev ⟨idx.1, hlt⟩)
    · have heq : idx.1 = t := by omega
      have : pairs ⟨idx.1, by omega⟩ = p := by
        simp [p, heq]
      rw [this]
      exact hnew

end Circ

/-! ### 2. Samuelson-Berkowitz identity via formal power series -/

section BerkowitzAlgebra

variable {S : Type*} [CommRing S]

/-- The reversed characteristic power series `q(A) = det(1 - X · A) ∈ PowerSeries S`. -/
noncomputable def revCharSeries {n : ℕ} (A : Matrix (Fin n) (Fin n) S) : PowerSeries S :=
  ((1 : Matrix (Fin n) (Fin n) (PowerSeries S)) -
    (PowerSeries.X : PowerSeries S) • A.map PowerSeries.C).det

/-- Coefficient of `X^n` in `∏_{i ∈ s} (C(a i) - X * C(b i))` when `s.card = n` is `(-1)^n ∏_{i ∈ s} b i`. -/
private theorem coeff_prod_linear {ι : Type*} (s : Finset ι) (a b : ι → S) :
    (∀ k > s.card, PowerSeries.coeff k (∏ i ∈ s, (PowerSeries.C (a i) - PowerSeries.X * PowerSeries.C (b i))) = 0) ∧
    PowerSeries.coeff s.card (∏ i ∈ s, (PowerSeries.C (a i) - PowerSeries.X * PowerSeries.C (b i))) =
      (-1 : S) ^ s.card * ∏ i ∈ s, b i := by
  classical
  induction s using Finset.induction_on with
  | empty =>
    refine ⟨fun k hk => ?_, by simp⟩
    simp only [Finset.card_empty] at hk
    simp [PowerSeries.coeff_one, Nat.ne_of_gt hk]
  | insert x s hx ih =>
    obtain ⟨ih_gt, ih_eq⟩ := ih
    rw [Finset.card_insert_of_notMem hx, Finset.prod_insert hx, Finset.prod_insert hx]
    have hmul : ∀ m, PowerSeries.coeff m ((PowerSeries.C (a x) - PowerSeries.X * PowerSeries.C (b x)) *
        ∏ i ∈ s, (PowerSeries.C (a i) - PowerSeries.X * PowerSeries.C (b i))) =
        a x * PowerSeries.coeff m (∏ i ∈ s, (PowerSeries.C (a i) - PowerSeries.X * PowerSeries.C (b i))) -
        (if m = 0 then 0 else b x * PowerSeries.coeff (m - 1)
          (∏ i ∈ s, (PowerSeries.C (a i) - PowerSeries.X * PowerSeries.C (b i)))) := by
      intro m
      rw [sub_mul, map_sub, PowerSeries.coeff_C_mul]
      congr 1
      cases m with
      | zero => simp
      | succ m =>
        rw [mul_assoc, PowerSeries.coeff_succ_X_mul, PowerSeries.coeff_C_mul]
        simp
    refine ⟨fun k hk => ?_, ?_⟩
    · rw [hmul k, ih_gt k (by omega)]
      have hk0 : k ≠ 0 := by omega
      rw [if_neg hk0, ih_gt (k - 1) (by omega)]
      ring
    · rw [hmul (s.card + 1), ih_gt (s.card + 1) (by omega)]
      simp only [Nat.succ_ne_zero, ↓reduceIte, Nat.add_sub_cancel, ih_eq]
      rw [pow_succ']
      ring

/-- The degree-`n` coefficient of `revCharSeries A` is `(-1)^n * A.det`. -/
theorem coeff_revCharSeries_top {n : ℕ} (A : Matrix (Fin n) (Fin n) S) :
    PowerSeries.coeff n (revCharSeries A) = (-1 : S) ^ n * A.det := by
  classical
  unfold revCharSeries
  rw [Matrix.det_apply, Matrix.det_apply, map_sum, Finset.mul_sum]
  refine Finset.sum_congr rfl fun σ _ => ?_
  rw [Units.smul_def, zsmul_eq_mul, Units.smul_def, zsmul_eq_mul]
  let Mps : Matrix (Fin n) (Fin n) (PowerSeries S) :=
    (1 : Matrix (Fin n) (Fin n) (PowerSeries S)) - (PowerSeries.X : PowerSeries S) • A.map PowerSeries.C
  have hcast : (PowerSeries.coeff n) (((Equiv.Perm.sign σ : ℤ) : PowerSeries S) *
      ∏ i : Fin n, Mps (σ i) i) =
      ((Equiv.Perm.sign σ : ℤ) : S) *
      PowerSeries.coeff n (∏ i : Fin n, Mps (σ i) i) := by
    rw [show ((Equiv.Perm.sign σ : ℤ) : PowerSeries S) = PowerSeries.C ((Equiv.Perm.sign σ : ℤ) : S) by simp,
      PowerSeries.coeff_C_mul]
  rw [hcast]
  have hterm : (∏ i : Fin n, Mps (σ i) i) =
      ∏ i : Fin n, (PowerSeries.C ((1 : Matrix (Fin n) (Fin n) S) (σ i) i) -
        PowerSeries.X * PowerSeries.C (A (σ i) i)) := by
    refine Finset.prod_congr rfl fun i _ => ?_
    simp [Mps, Matrix.one_apply]
  rw [hterm]
  have htop := (coeff_prod_linear Finset.univ
    (fun i => (1 : Matrix (Fin n) (Fin n) S) (σ i) i) (fun i => A (σ i) i)).2
  simp only [Finset.card_univ, Fintype.card_fin] at htop
  rw [htop]
  ring

/-- The Neumann inverse power series matrix `S(M)_{ij} = ∑_{k≥0} (M^k)_{ij} X^k`. -/
noncomputable def neumannSeries {n : ℕ} (M : Matrix (Fin n) (Fin n) S) :
    Matrix (Fin n) (Fin n) (PowerSeries S) :=
  Matrix.of fun i j => PowerSeries.mk fun k => (M ^ k) i j

/-- `(1 - X • M) * neumannSeries M = 1` over ANY commutative ring `S`! -/
theorem one_sub_X_mul_neumann {n : ℕ} (M : Matrix (Fin n) (Fin n) S) :
    ((1 : Matrix (Fin n) (Fin n) (PowerSeries S)) -
      (PowerSeries.X : PowerSeries S) • M.map PowerSeries.C) * neumannSeries M = 1 := by
  ext i j k
  simp only [Matrix.mul_apply, Matrix.sub_apply, Matrix.one_apply, Matrix.smul_apply,
    Matrix.map_apply, smul_eq_mul, neumannSeries, Matrix.of_apply, map_sum]
  cases k with
  | zero =>
    have h0 : ∀ l : Fin n, PowerSeries.coeff 0 (((if i = l then (1 : PowerSeries S) else 0) -
        PowerSeries.X * PowerSeries.C (M i l)) * PowerSeries.mk fun m => (M ^ m) l j) =
        if i = l then (M ^ 0) l j else 0 := by
      intro l
      rw [sub_mul, map_sub, mul_assoc, PowerSeries.coeff_zero_X_mul, sub_zero]
      split_ifs <;> simp
    simp only [h0, Finset.sum_ite_eq, Finset.mem_univ, ↓reduceIte, pow_zero, Matrix.one_apply]
    split_ifs <;> simp
  | succ k =>
    have hs : ∀ l : Fin n, PowerSeries.coeff (k + 1) (((if i = l then (1 : PowerSeries S) else 0) -
        PowerSeries.X * PowerSeries.C (M i l)) * PowerSeries.mk fun m => (M ^ m) l j) =
        (if i = l then (M ^ (k + 1)) l j else 0) - M i l * (M ^ k) l j := by
      intro l
      rw [sub_mul, map_sub, mul_assoc, PowerSeries.coeff_succ_X_mul, PowerSeries.coeff_C_mul,
        PowerSeries.coeff_mk]
      congr 1
      split_ifs <;> simp
    simp only [hs, Finset.sum_sub_distrib, Finset.sum_ite_eq, Finset.mem_univ, ↓reduceIte]
    have hpow : (M ^ (k + 1)) i j = ∑ l : Fin n, M i l * (M ^ k) l j := by
      rw [pow_succ', Matrix.mul_apply]
    rw [hpow, sub_self]
    split_ifs <;> simp

/-- Leading principal `(n × n)` submatrix (indices `1..n`) of an `(n+1) × (n+1)` matrix. -/
def subM {n : ℕ} (A : Matrix (Fin (n + 1)) (Fin (n + 1)) S) : Matrix (Fin n) (Fin n) S :=
  Matrix.of fun i j => A i.succ j.succ

/-- Top row `r_j = A 0 (j.succ)`. -/
def topR {n : ℕ} (A : Matrix (Fin (n + 1)) (Fin (n + 1)) S) : Fin n → S :=
  fun j => A 0 j.succ

/-- Left column `c_i = A (i.succ) 0`. -/
def leftC {n : ℕ} (A : Matrix (Fin (n + 1)) (Fin (n + 1)) S) : Fin n → S :=
  fun i => A i.succ 0

/-- Berkowitz factor power series for an `(n+1) × (n+1)` matrix `A`:
`1 - A_{0,0} X - ∑_{j≥0} (r · M^j · c) X^{j+2}`. -/
noncomputable def berkFactor {n : ℕ} (A : Matrix (Fin (n + 1)) (Fin (n + 1)) S) : PowerSeries S :=
  PowerSeries.mk fun t =>
    match t with
    | 0 => 1
    | 1 => -A 0 0
    | j + 2 => -(∑ i : Fin n, topR A i * ((subM A ^ j).mulVec (leftC A) i))

/-- **Samuelson-Berkowitz Identity:**
`revCharSeries A = berkFactor A * revCharSeries (subM A)` over ANY commutative ring `S`! -/
theorem revCharSeries_succ {n : ℕ} (A : Matrix (Fin (n + 1)) (Fin (n + 1)) S) :
    revCharSeries A = berkFactor A * revCharSeries (subM A) := by
  -- Reindex `Fin (n + 1)` as `Fin 1 ⊕ Fin n` via `finSumFinEquiv`.
  let e : Fin 1 ⊕ Fin n ≃ Fin (n + 1) := finSumFinEquiv.trans (finCongr (by omega))
  have he0 : e (Sum.inl 0) = 0 := by
    ext
    simp [e, finSumFinEquiv]
  have hes : ∀ i : Fin n, e (Sum.inr i) = i.succ := by
    intro i
    ext
    simp [e, finSumFinEquiv]
  let B : Matrix (Fin (n + 1)) (Fin (n + 1)) (PowerSeries S) :=
    (1 : Matrix (Fin (n + 1)) (Fin (n + 1)) (PowerSeries S)) -
      (PowerSeries.X : PowerSeries S) • A.map PowerSeries.C
  let B11 : Matrix (Fin 1) (Fin 1) (PowerSeries S) :=
    Matrix.of fun _ _ => 1 - PowerSeries.X * PowerSeries.C (A 0 0)
  let B12 : Matrix (Fin 1) (Fin n) (PowerSeries S) :=
    Matrix.of fun _ j => -(PowerSeries.X * PowerSeries.C (topR A j))
  let B21 : Matrix (Fin n) (Fin 1) (PowerSeries S) :=
    Matrix.of fun i _ => -(PowerSeries.X * PowerSeries.C (leftC A i))
  let B22 : Matrix (Fin n) (Fin n) (PowerSeries S) :=
    (1 : Matrix (Fin n) (Fin n) (PowerSeries S)) -
      (PowerSeries.X : PowerSeries S) • (subM A).map PowerSeries.C
  have hB : B.submatrix e e = Matrix.fromBlocks B11 B12 B21 B22 := by
    ext x y
    rcases x with i | i <;> rcases y with j | j
    · fin_cases i; fin_cases j
      simp [B, B11, he0, smul_eq_mul]
    · fin_cases i
      have hne : (0 : Fin (n + 1)) ≠ j.succ := (Fin.succ_ne_zero j).symm
      simp [B, B12, he0, hes, topR, hne, smul_eq_mul]
    · fin_cases j
      have hne : i.succ ≠ (0 : Fin (n + 1)) := Fin.succ_ne_zero i
      simp [B, B21, he0, hes, leftC, hne, smul_eq_mul]
    · simp [B, B22, hes, subM, Matrix.one_apply, smul_eq_mul]
  -- Right-multiply by unit-determinant block lower-triangular matrix `U`:
  --   fromBlocks B11 B12 B21 B22 * fromBlocks 1 0 (-neumannSeries (subM A) * B21) 1
  --   = fromBlocks (B11 - B12 * neumannSeries (subM A) * B21) B12 0 B22
  let U21 : Matrix (Fin n) (Fin 1) (PowerSeries S) := -(neumannSeries (subM A) * B21)
  let U : Matrix (Fin 1 ⊕ Fin n) (Fin 1 ⊕ Fin n) (PowerSeries S) := Matrix.fromBlocks 1 0 U21 1
  have hdetU : U.det = 1 := by
    simp [U]
  have hprod : Matrix.fromBlocks B11 B12 B21 B22 * U =
      Matrix.fromBlocks (B11 + B12 * U21) B12 0 B22 := by
    rw [Matrix.fromBlocks_multiply]
    congr 1
    · simp
    · simp
    · simp only [U21, Matrix.mul_one, Matrix.mul_neg, ← Matrix.mul_assoc]
      have hinv : B22 * neumannSeries (subM A) = 1 := one_sub_X_mul_neumann (subM A)
      rw [hinv, Matrix.one_mul, add_neg_cancel]
    · simp
  have hdet_eq : revCharSeries A = (B11 + B12 * U21).det * revCharSeries (subM A) := by
    have h1 : revCharSeries A = (B.submatrix e e).det := by
      unfold revCharSeries
      exact (Matrix.det_reindex_self e.symm B).symm
    rw [h1, hB]
    have h2 : (Matrix.fromBlocks B11 B12 B21 B22).det =
        (Matrix.fromBlocks B11 B12 B21 B22 * U).det := by
      rw [Matrix.det_mul, hdetU, mul_one]
    rw [h2, hprod, Matrix.det_fromBlocks_zero₂₁]
    rfl
  rw [hdet_eq]
  congr 1
  -- Show `(B11 + B12 * U21).det = berkFactor A`!
  rw [Matrix.det_fin_one]
  apply PowerSeries.ext
  intro t
  simp only [Matrix.add_apply, Matrix.mul_apply, B11, B12, U21, B21, Matrix.neg_apply,
    Matrix.of_apply, neumannSeries, berkFactor, PowerSeries.coeff_mk]
  have hterm : (∑ j : Fin n, -(PowerSeries.X * PowerSeries.C (topR A j)) *
      -(∑ l : Fin n, (PowerSeries.mk fun k => (subM A ^ k) j l) * -(PowerSeries.X * PowerSeries.C (leftC A l)))) =
      -(PowerSeries.X * (PowerSeries.X * PowerSeries.mk fun k =>
        ∑ j : Fin n, topR A j * ((subM A ^ k).mulVec (leftC A) j))) := by
    apply PowerSeries.ext
    intro m
    simp only [mul_neg, neg_mul, neg_neg, Finset.sum_neg_distrib, map_neg, map_sum]
    congr 1
    cases m with
    | zero =>
      simp only [PowerSeries.coeff_zero_X_mul]
      refine Finset.sum_eq_zero fun j _ => ?_
      rw [mul_assoc, PowerSeries.coeff_zero_X_mul]
    | succ m =>
      cases m with
      | zero =>
        simp only [PowerSeries.coeff_succ_X_mul, PowerSeries.coeff_zero_X_mul]
        refine Finset.sum_eq_zero fun j _ => ?_
        rw [mul_assoc, PowerSeries.coeff_succ_X_mul, PowerSeries.coeff_C_mul, map_sum]
        refine mul_eq_zero_of_right _ (Finset.sum_eq_zero fun l _ => ?_)
        rw [mul_comm, mul_assoc, PowerSeries.coeff_zero_X_mul]
      | succ k =>
        simp only [PowerSeries.coeff_succ_X_mul, PowerSeries.coeff_mk, Matrix.mulVec, dotProduct]
        refine Finset.sum_congr rfl fun j _ => ?_
        rw [mul_assoc, PowerSeries.coeff_succ_X_mul, PowerSeries.coeff_C_mul, map_sum]
        congr 1
        refine Finset.sum_congr rfl fun l _ => ?_
        rw [mul_comm _ (PowerSeries.X * PowerSeries.C (leftC A l)), mul_assoc,
          PowerSeries.coeff_succ_X_mul, PowerSeries.coeff_C_mul, PowerSeries.coeff_mk, mul_comm]
  rw [hterm]
  cases t with
  | zero =>
    simp
  | succ t =>
    cases t with
    | zero =>
      simp [PowerSeries.coeff_succ_X_mul, PowerSeries.coeff_zero_X_mul]
    | succ j =>
      simp [PowerSeries.coeff_succ_X_mul, PowerSeries.coeff_mk, PowerSeries.coeff_X]

/-- Coefficient recurrence for `revCharSeries A` directly from `revCharSeries_succ`. -/
theorem coeff_revCharSeries_succ {n : ℕ} (A : Matrix (Fin (n + 1)) (Fin (n + 1)) S) (t : ℕ) :
    PowerSeries.coeff t (revCharSeries A) =
      ∑ u : Fin (t + 1), PowerSeries.coeff u.1 (berkFactor A) *
        PowerSeries.coeff (t - u.1) (revCharSeries (subM A)) := by
  rw [revCharSeries_succ A, PowerSeries.coeff_mul, Finset.Nat.sum_antidiagonal_eq_sum_range_succ_mk]
  rw [← Fin.sum_univ_eq_sum_range]

end BerkowitzAlgebra

/-! ### 3. Polynomial-size Berkowitz circuit over any commutative ring -/

section BerkowitzCircuit

variable {R : Type u} {V : Type} [CommRing R]

/-- Compute `M *ᵥ v` for an `n × n` matrix `M` and vector `v` already in `C`,
adding at most `n * (2 * n + 1)` gates. -/
theorem Circ.exists_mulVec (C : Circ R V) {n : ℕ}
    (M : Matrix (Fin n) (Fin n) (MvPolynomial V R))
    (v : Fin n → MvPolynomial V R)
    (hM : ∀ i j, M i j ∈ C.gates) (hv : ∀ j, v j ∈ C.gates) :
    ∃ C' : Circ R V, Circ.Extends C C' ∧ (∀ i, M.mulVec v i ∈ C'.gates) ∧
      C'.gates.length ≤ C.gates.length + n * (2 * n + 1) := by
  suffices h : ∀ k (hk : k ≤ n),
      ∃ C' : Circ R V, Circ.Extends C C' ∧
        (∀ i : Fin k, M.mulVec v ⟨i.1, by omega⟩ ∈ C'.gates) ∧
        C'.gates.length ≤ C.gates.length + k * (2 * n + 1) by
    obtain ⟨C', hE, hm, hl⟩ := h n le_rfl
    exact ⟨C', hE, hm, hl⟩
  intro k hk
  induction k with
  | zero => exact ⟨C, Circ.Extends.refl C, fun i => Fin.elim0 i, by omega⟩
  | succ k ih =>
    obtain ⟨C₁, h₁, hprev, hl₁⟩ := ih (by omega)
    obtain ⟨C₂, h₂, hdot, hl₂⟩ := Circ.exists_dotProduct C₁ (fun j => M ⟨k, by omega⟩ j) v
      (fun j => h₁ _ (hM _ j)) (fun j => h₁ _ (hv j))
    refine ⟨C₂, h₁.trans h₂, fun i => ?_, by
      have : (k + 1) * (2 * n + 1) = k * (2 * n + 1) + (2 * n + 1) := by ring
      omega⟩
    by_cases hlt : i.1 < k
    · exact h₂ _ (hprev ⟨i.1, hlt⟩)
    · have heq : i.1 = k := by omega
      have : (⟨i.1, by omega⟩ : Fin n) = ⟨k, by omega⟩ := Fin.ext heq
      rw [this]
      exact hdot

/-- Compute all vectors `(M ^ j).mulVec c` for `j < n`, adding at most `n * n * (2 * n + 1)` gates. -/
theorem Circ.exists_powMulVec (C : Circ R V) {n : ℕ}
    (M : Matrix (Fin n) (Fin n) (MvPolynomial V R))
    (c : Fin n → MvPolynomial V R)
    (hM : ∀ i j, M i j ∈ C.gates) (hc : ∀ i, c i ∈ C.gates) :
    ∃ C' : Circ R V, Circ.Extends C C' ∧
      (∀ j : ℕ, j < n → ∀ i, (M ^ j).mulVec c i ∈ C'.gates) ∧
      C'.gates.length ≤ C.gates.length + n * n * (2 * n + 1) := by
  suffices h : ∀ k (hk : k ≤ n),
      ∃ C' : Circ R V, Circ.Extends C C' ∧
        (∀ j < k, ∀ i, (M ^ j).mulVec c i ∈ C'.gates) ∧
        C'.gates.length ≤ C.gates.length + k * n * (2 * n + 1) by
    exact h n le_rfl
  intro k hk
  induction k with
  | zero => exact ⟨C, Circ.Extends.refl C, fun _ hj => absurd hj (Nat.not_lt_zero _), by omega⟩
  | succ k ih =>
    cases k with
    | zero =>
      refine ⟨C, Circ.Extends.refl C, fun j hj i => ?_, by omega⟩
      have hj0 : j = 0 := by omega
      subst hj0
      simpa using hc i
    | succ k =>
      obtain ⟨C₁, h₁, hprev, hl₁⟩ := ih (by omega)
      obtain ⟨C₂, h₂, hnext, hl₂⟩ := Circ.exists_mulVec C₁ M ((M ^ k).mulVec c)
        (fun i j => h₁ _ (hM i j)) (hprev k (by omega))
      refine ⟨C₂, h₁.trans h₂, fun j hj i => ?_, by
        have : (k + 1 + 1) * n * (2 * n + 1) = (k + 1) * n * (2 * n + 1) + n * (2 * n + 1) := by ring
        omega⟩
      by_cases hlt : j < k + 1
      · exact h₂ _ (hprev j hlt i)
      · have heq : j = k + 1 := by omega
        subst heq
        have hstep : (M ^ (k + 1)).mulVec c i = M.mulVec ((M ^ k).mulVec c) i := by
          rw [pow_succ', Matrix.mulVec_mulVec]
        rw [hstep]
        exact hnext i

/-- Compute all Berkowitz factor coefficients `coeff u (berkFactor A)` for `u ≤ n + 1`
in at most `n * n * (2 * n + 1) + n * (2 * n + 3) + 3` extra gates. -/
theorem Circ.exists_berkFactor (C : Circ R V) {n : ℕ}
    (A : Matrix (Fin (n + 1)) (Fin (n + 1)) (MvPolynomial V R))
    (hA : ∀ i j, A i j ∈ C.gates) :
    ∃ C' : Circ R V, Circ.Extends C C' ∧
      (∀ u ≤ n + 1, PowerSeries.coeff u (berkFactor A) ∈ C'.gates) ∧
      C'.gates.length ≤ C.gates.length + n * n * (2 * n + 1) + n * (2 * n + 3) + 3 := by
  obtain ⟨C₁, h₁, hpv, hl₁⟩ := Circ.exists_powMulVec C (subM A) (leftC A)
    (fun i j => hA i.succ j.succ) (fun i => hA i.succ 0)
  obtain ⟨C₂, h₂, h1g, hl₂⟩ := Circ.exists_addC C₁ (1 : R)
  obtain ⟨C₃, h₃, hneg0, hl₃⟩ := Circ.exists_addNeg C₂ ((h₁.trans h₂) _ (hA 0 0))
  -- Compute `-(∑ i, topR A i * (subM A ^ j).mulVec (leftC A) i)` for all `j < n`.
  suffices hdots : ∀ k (hk : k ≤ n),
      ∃ C' : Circ R V, Circ.Extends C₃ C' ∧
        (∀ j < k, -(∑ i : Fin n, topR A i * ((subM A ^ j).mulVec (leftC A) i)) ∈ C'.gates) ∧
        C'.gates.length ≤ C₃.gates.length + k * (2 * n + 3) by
    obtain ⟨C₄, h₄, hsc, hl₄⟩ := hdots n le_rfl
    refine ⟨C₄, h₁.trans (h₂.trans (h₃.trans h₄)), fun u hu => ?_, by omega⟩
    unfold berkFactor
    rw [PowerSeries.coeff_mk]
    match u with
    | 0 => exact (h₃.trans h₄) _ (by simpa using h1g)
    | 1 => exact h₄ _ hneg0
    | j + 2 => exact hsc j (by omega)
  intro k hk
  induction k with
  | zero => exact ⟨C₃, Circ.Extends.refl C₃, fun _ hj => absurd hj (Nat.not_lt_zero _), by omega⟩
  | succ k ih =>
    obtain ⟨C₄, h₄, hprev, hl₄⟩ := ih (by omega)
    have hE3 : Circ.Extends C C₄ := h₁.trans (h₂.trans (h₃.trans h₄))
    have hE1 : Circ.Extends C₁ C₄ := h₂.trans (h₃.trans h₄)
    obtain ⟨C₅, h₅, hdot, hl₅⟩ := Circ.exists_dotProduct C₄ (topR A) ((subM A ^ k).mulVec (leftC A))
      (fun i => hE3 _ (hA 0 i.succ)) (fun i => hE1 _ (hpv k (by omega) i))
    obtain ⟨C₆, h₆, hneg, hl₆⟩ := Circ.exists_addNeg C₅ hdot
    refine ⟨C₆, h₄.trans (h₅.trans h₆), fun j hj => ?_, by
      have : (k + 1) * (2 * n + 3) = k * (2 * n + 3) + (2 * n + 3) := by ring
      omega⟩
    by_cases hlt : j < k
    · exact (h₅.trans h₆) _ (hprev j hlt)
    · have heq : j = k := by omega
      subst heq
      exact hneg

/-- **Berkowitz's polynomial-size determinant circuit:**
Given a circuit `C` containing all entries of an `n × n` matrix `A`, there is an
extension `C'` of size at most `C.gates.length + 10 * (n + 1)^4` computing all
coefficients `coeff t (revCharSeries A)` for `t ≤ n`. -/
theorem Circ.exists_revCharSeries (n : ℕ) (C : Circ R V)
    (A : Matrix (Fin n) (Fin n) (MvPolynomial V R)) (hA : ∀ i j, A i j ∈ C.gates) :
    ∃ C' : Circ R V, Circ.Extends C C' ∧
      (∀ t ≤ n, PowerSeries.coeff t (revCharSeries A) ∈ C'.gates) ∧
      C'.gates.length ≤ C.gates.length + 10 * (n + 1) ^ 4 := by
  induction n generalizing C with
  | zero =>
    obtain ⟨C₁, h₁, h1g, hl₁⟩ := Circ.exists_addC C (1 : R)
    refine ⟨C₁, h₁, fun t ht => ?_, by omega⟩
    have ht0 : t = 0 := by omega
    subst ht0
    have hdet : revCharSeries A = 1 := by
      unfold revCharSeries
      simp [Matrix.det_isEmpty]
    rw [hdet]
    simpa using h1g
  | succ n ih =>
    -- Step 1: Recursively compute `coeff t (revCharSeries (subM A))` for `t ≤ n`.
    obtain ⟨C₁, h₁, hsub, hl₁⟩ := ih C (subM A) (fun i j => hA i.succ j.succ)
    -- Step 2: Compute `coeff u (berkFactor A)` for `u ≤ n + 1`.
    obtain ⟨C₂, h₂, hbf, hl₂⟩ := Circ.exists_berkFactor C₁ A (fun i j => h₁ _ (hA i j))
    -- Step 3: Compute the `n + 2` convolution dot products for `t = 0..n+1`.
    -- Note for `t = n + 1`, the term `u = 0` uses `coeff (n + 1) (revCharSeries (subM A)) = 0`!
    -- Even simpler: first add `0` to `C₂`, so `coeff m (revCharSeries (subM A)) ∈ C₃` for ALL `m ≤ n + 1`!
    obtain ⟨C₃, h₃, h0g, hl₃⟩ := Circ.exists_addC C₂ (0 : R)
    have hsub_all : ∀ m ≤ n + 1, PowerSeries.coeff m (revCharSeries (subM A)) ∈ C₃.gates := by
      intro m hm
      by_cases hle : m ≤ n
      · exact (h₂.trans h₃) _ (hsub m hle)
      · have hgt : m > n := by omega
        -- Prove `coeff m (revCharSeries (subM A)) = 0` for `m > n`!
        have hzero : PowerSeries.coeff m (revCharSeries (subM A)) = 0 := by
          unfold revCharSeries
          rw [Matrix.det_apply, map_sum]
          refine Finset.sum_eq_zero fun σ _ => ?_
          rw [Units.smul_def, zsmul_eq_mul,
            show ((Equiv.Perm.sign σ : ℤ) : PowerSeries (MvPolynomial V R)) =
              PowerSeries.C ((Equiv.Perm.sign σ : ℤ) : MvPolynomial V R) by simp,
            PowerSeries.coeff_C_mul]
          let Msub : Matrix (Fin n) (Fin n) (PowerSeries (MvPolynomial V R)) :=
            (1 : Matrix (Fin n) (Fin n) (PowerSeries (MvPolynomial V R))) -
              (PowerSeries.X : PowerSeries (MvPolynomial V R)) • (subM A).map PowerSeries.C
          have hterm : (∏ i : Fin n, Msub (σ i) i) =
              ∏ i : Fin n, (PowerSeries.C ((1 : Matrix (Fin n) (Fin n) (MvPolynomial V R)) (σ i) i) -
                PowerSeries.X * PowerSeries.C (subM A (σ i) i)) := by
            refine Finset.prod_congr rfl fun i _ => ?_
            simp [Msub, Matrix.one_apply]
          rw [hterm]
          have h0 := (coeff_prod_linear Finset.univ
            (fun i => (1 : Matrix (Fin n) (Fin n) (MvPolynomial V R)) (σ i) i)
            (fun i => subM A (σ i) i)).1 m (by simpa using hgt)
          rw [h0, mul_zero]
        rw [hzero]
        simpa using h0g
    -- Loop over `t = 0..n+1`, computing each convolution dot product of length `t + 1 ≤ n + 2`.
    suffices hconv : ∀ k (hk : k ≤ n + 2),
        ∃ C' : Circ R V, Circ.Extends C₃ C' ∧
          (∀ t < k, PowerSeries.coeff t (revCharSeries A) ∈ C'.gates) ∧
          C'.gates.length ≤ C₃.gates.length + k * (2 * (n + 2) + 1) by
      obtain ⟨C₄, h₄, hres, hl₄⟩ := hconv (n + 2) le_rfl
      refine ⟨C₄, h₁.trans (h₂.trans (h₃.trans h₄)), fun t ht => hres t (by omega), ?_⟩
      -- Arithmetic bound: `10*(n+1)^4 + n^2*(2n+1) + n*(2n+3) + 4 + (n+2)*(2n+5) <= 10*(n+1+1)^4`!
      have hpoly : 10 * (n + 1) ^ 4 + n * n * (2 * n + 1) + n * (2 * n + 3) + 4 +
          (n + 2) * (2 * (n + 2) + 1) ≤ 10 * (n + 1 + 1) ^ 4 := by
        zify
        nlinarith [sq_nonneg (n : ℤ), sq_nonneg ((n : ℤ) ^ 2)]
      omega
    intro k hk
    induction k with
    | zero => exact ⟨C₃, Circ.Extends.refl C₃, fun _ ht => absurd ht (Nat.not_lt_zero _), by omega⟩
    | succ k ihk =>
      obtain ⟨C₄, h₄, hprev, hl₄⟩ := ihk (by omega)
      obtain ⟨C₅, h₅, hdot, hl₅⟩ := Circ.exists_dotProduct C₄
        (fun u : Fin (k + 1) => PowerSeries.coeff u.1 (berkFactor A))
        (fun u : Fin (k + 1) => PowerSeries.coeff (k - u.1) (revCharSeries (subM A)))
        (fun u => (h₃.trans h₄) _ (hbf u.1 (by omega)))
        (fun u => h₄ _ (hsub_all (k - u.1) (by omega)))
      refine ⟨C₅, h₄.trans h₅, fun t ht => ?_, by
        have hstep : 2 * (k + 1) + 1 ≤ 2 * (n + 2) + 1 := by omega
        have : (k + 1) * (2 * (n + 2) + 1) = k * (2 * (n + 2) + 1) + (2 * (n + 2) + 1) := by ring
        omega⟩
      by_cases hlt : t < k
      · exact h₅ _ (hprev t hlt)
      · have heq : t = k := by omega
        subst heq
        rw [coeff_revCharSeries_succ A t]
        exact hdot

/-- **Theorem (Berkowitz circuit for affine matrices):**
The determinant of any `k × k` affine matrix over `MvPolynomial V R` (with `V` finite)
has an arithmetic circuit of size `k^2 (4 |V| + 2) + 10 (k + 1)^4 + 2`. -/
theorem computes_det_of_affine [Fintype V] {k : ℕ}
    (M : Matrix (Fin k) (Fin k) (MvPolynomial V R))
    (hM : ∀ i j, (M i j).totalDegree ≤ 1) :
    Statement.Computes M.det (k * k * (4 * Fintype.card V + 2) + 10 * (k + 1) ^ 4 + 2) := by
  obtain ⟨C₁, -, hmat, hl₁⟩ := Circ.exists_affineMatrix (Circ.empty (R := R) (V := V)) M hM
  obtain ⟨C₂, -, hrc, hl₂⟩ := Circ.exists_revCharSeries k C₁ M hmat
  obtain ⟨C₃, h₃, hsgn, hl₃⟩ := Circ.exists_addC C₂ ((-1 : R) ^ k)
  obtain ⟨C₄, -, hdet, hl₄⟩ := Circ.exists_addMul C₃ hsgn (h₃ _ (hrc k le_rfl))
  have hdet_eq : MvPolynomial.C ((-1 : R) ^ k) * PowerSeries.coeff k (revCharSeries M) = M.det := by
    rw [coeff_revCharSeries_top M, ← mul_assoc]
    have hpow : MvPolynomial.C ((-1 : R) ^ k) * (-1 : MvPolynomial V R) ^ k = 1 := by
      rw [map_pow, map_neg, map_one, ← mul_pow]
      simp
    rw [hpow, one_mul]
  rw [hdet_eq] at hdet
  have hcomp := C₄.toComputes hdet
  have hlen : C₄.gates.length ≤ k * k * (4 * Fintype.card V + 2) + 10 * (k + 1) ^ 4 + 2 := by
    simp only [Circ.empty, List.length_nil, zero_add] at hl₁
    omega
  -- Monotonicity of `Statement.Computes` in gate bound `s`
  obtain ⟨l, hl_valid, idx, hidx, hidx_eq⟩ := hcomp
  refine ⟨fun t => if t < C₄.gates.length then l t else MvPolynomial.C 0, fun t ht => ?_,
    idx, hidx.trans_le hlen, by simpa [hidx] using hidx_eq⟩
  by_cases hlt : t < C₄.gates.length
  · simp only [if_pos hlt]
    rcases hl_valid t hlt with h | h | ⟨i, hi, j, hj, h⟩ | ⟨i, hi, j, hj, h⟩
    · exact Or.inl h
    · exact Or.inr (Or.inl h)
    · exact Or.inr (Or.inr (Or.inl ⟨i, hi, j, hj, by
        simp [hi.trans hlt, hj.trans hlt, h]⟩))
    · exact Or.inr (Or.inr (Or.inr ⟨i, hi, j, hj, by
        simp [hi.trans hlt, hj.trans hlt, h]⟩))
  · exact Or.inr (Or.inl ⟨0, by simp [hlt]⟩)

end BerkowitzCircuit

/-! ### 4. Remark N.6: Superpolynomial Border Determinantal Complexity of `perm` -/

/-- `f` is approximated (in the sense of Definition N.1 / `Statement.Approximates`) by the
determinant of a `k × k` affine matrix over `LaurentSeries F`. -/
def BorderDetApprox {F : Type u} {V : Type} [Field F] (f : MvPolynomial V F) (k : ℕ) : Prop :=
  ∃ M : Matrix (Fin k) (Fin k) (MvPolynomial V (LaurentSeries F)),
    (∀ i j, (M i j).totalDegree ≤ 1) ∧
    ∀ (d : V →₀ ℕ) (i : ℤ), i ≤ 0 →
      (coeff d M.det).coeff i = if i = 0 then coeff d f else 0

/-- **Remark N.6 (Border determinantal complexity of the permanent), conditional on `MainTheoremApprox`:**
Over every field of characteristic other than two, there is an absolute constant `c > 0`
(and for each characteristic `p ≠ 2` a threshold `m₀`) such that for all `m ≥ m₀`,
`perm F m` is NOT approximated by the determinant of any affine matrix of size at most
`m ^ (c * (log₂ m) ^ (1 / 3))`. -/
theorem remarkN6_of_mainTheoremApprox (happrox_thm : Statement.MainTheoremApprox.{u}) :
    ∃ c : ℝ, 0 < c ∧ ∀ p : ℕ, p ≠ 2 → ∃ m₀ : ℕ,
      ∀ (F : Type u) [Field F] [CharP F p], ∀ m ≥ m₀, ∀ k : ℕ,
        BorderDetApprox (Statement.perm F m) k → Statement.Beyond c m k := by
  obtain ⟨c₀, hc₀, hmain⟩ := happrox_thm
  refine ⟨c₀ / 5, by linarith, fun p hp => ?_⟩
  obtain ⟨m₁, hm₁⟩ := hmain p
  -- Pick `m₂` so large that for all `m ≥ m₂`:
  --   `c₀ / 5 * (log₂ m)^(1/3) ≥ 1`  AND  `m ^ (c₀ / 5 * (log₂ m)^(1/3)) > 2000`
  have htend : Filter.Tendsto (fun m : ℕ => (c₀ / 5) * Real.logb 2 m ^ (1 / 3 : ℝ))
      Filter.atTop Filter.atTop :=
    ((tendsto_rpow_atTop (by norm_num : (0 : ℝ) < 1 / 3)).comp
      ((Real.tendsto_logb_atTop (by norm_num : (1 : ℝ) < 2)).comp
        tendsto_natCast_atTop_atTop)).const_mul_atTop (by linarith)
  obtain ⟨m₂, hm₂⟩ := Filter.eventually_atTop.1 (htend.eventually_ge_atTop (1 : ℝ))
  refine ⟨max (max m₁ m₂) 2000, fun F _ _ m hm k ⟨M, hM_aff, hM_approx⟩ => ?_⟩
  have hm1 : m₁ ≤ m := le_trans (le_trans (le_max_left _ _) (le_max_left _ _)) hm
  have hm2 : m₂ ≤ m := le_trans (le_trans (le_max_right _ _) (le_max_left _ _)) hm
  have hm2000 : 2000 ≤ m := le_trans (le_max_right _ _) hm
  -- Convert the `k × k` affine determinant approximation into an approximating circuit of size `S`.
  let S : ℕ := k * k * (4 * Fintype.card (Fin m × Fin m) + 2) + 10 * (k + 1) ^ 4 + 2
  have hcomp : Statement.Computes M.det S := computes_det_of_affine M hM_aff
  have happrox : Statement.Approximates (Statement.perm F m) S := ⟨M.det, hcomp, hM_approx⟩
  have hbeyond : Statement.Beyond c₀ m S := (hm₁ F m hm1 S).2 hp happrox
  unfold Statement.Beyond at hbeyond ⊢
  by_contra hle
  push Not at hle
  -- Let `E = (c₀ / 5) * (log₂ m)^(1/3) ≥ 1`, and `B = m ^ E ≥ m ≥ 2000`.
  set E : ℝ := c₀ / 5 * Real.logb 2 m ^ (1 / 3 : ℝ) with hE_def
  have hE1 : 1 ≤ E := hm₂ m hm2
  have hm_pos : (0 : ℝ) < (m : ℝ) := by positivity
  have hm_ge1 : (1 : ℝ) ≤ (m : ℝ) := by exact_mod_cast (by omega : 1 ≤ m)
  have hm_ge2000 : (2000 : ℝ) ≤ (m : ℝ) := by exact_mod_cast hm2000
  have hm_le_B : (m : ℝ) ≤ (m : ℝ) ^ E := by
    conv_lhs => rw [← Real.rpow_one (m : ℝ)]
    exact Real.rpow_le_rpow_of_exponent_le hm_ge1 hE1
  set B : ℝ := (m : ℝ) ^ E with hB_def
  have hB_ge2000 : 2000 ≤ B := hm_ge2000.trans hm_le_B
  have hB_pos : 0 < B := by linarith
  have hk0 : (0 : ℝ) ≤ (k : ℝ) := Nat.cast_nonneg k
  have hk_le : (k : ℝ) ≤ B := hle
  -- Bound `S` from above by `200 * B ^ 4 < B ^ 5 = m ^ (5 * E) = m ^ (c₀ * (log₂ m)^(1/3))`!
  have hS_real : (S : ℝ) = (k : ℝ) ^ 2 * (4 * (m : ℝ) ^ 2 + 2) + 10 * ((k : ℝ) + 1) ^ 4 + 2 := by
    simp only [S, Fintype.card_prod, Fintype.card_fin]
    push_cast
    ring
  have hS_le : (S : ℝ) ≤ 200 * B ^ 4 := by
    rw [hS_real]
    have h1 : (k : ℝ) ^ 2 ≤ B ^ 2 := by nlinarith
    have h2 : 4 * (m : ℝ) ^ 2 + 2 ≤ 5 * B ^ 2 := by nlinarith
    have h3 : (k : ℝ) + 1 ≤ 2 * B := by linarith
    have h4 : ((k : ℝ) + 1) ^ 4 ≤ (2 * B) ^ 4 := by
      exact pow_le_pow_left₀ (by positivity) h3 4
    have h5 : (2 : ℝ) ≤ B ^ 4 := by nlinarith [pow_two B]
    have h6 : (k : ℝ) ^ 2 * (4 * (m : ℝ) ^ 2 + 2) ≤ B ^ 2 * (5 * B ^ 2) := by
      exact mul_le_mul h1 h2 (by positivity) (by positivity)
    nlinarith
  have hB5 : 200 * B ^ 4 < B ^ 5 := by
    have hpow : B ^ 5 = B * B ^ 4 := by ring
    rw [hpow]
    nlinarith [pow_pos hB_pos 4]
  have hB5_eq : B ^ 5 = (m : ℝ) ^ (c₀ * Real.logb 2 m ^ (1 / 3 : ℝ)) := by
    rw [hB_def, ← Real.rpow_natCast, ← Real.rpow_mul hm_pos.le, hE_def]
    congr 1
    push_cast
    ring
  linarith

end RemarkN6
