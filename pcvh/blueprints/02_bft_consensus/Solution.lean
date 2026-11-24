import Specs.Bft.Statement

/-
  Blueprint 2 — Verified BFT Consensus & Merkle Proof Package (`Solution.lean`)
  Zero `sorry`, zero Mathlib, constructive standard axioms only.
-/

namespace Solution
open BftProto

private theorem count_bound_of_no_overlap (recs : List ValidatorVote)
    (h_no : ¬ hasHonestOverlap recs) :
    countQ1 recs + countQ2 recs ≤ recs.length + countByz recs := by
  induction recs with
  | nil =>
      simp [countQ1, countQ2, countByz]
  | cons r rest ih =>
      simp only [hasHonestOverlap] at h_no
      have h_head : ¬ (r.isByz = false ∧ r.inQ1 = true ∧ r.inQ2 = true) := fun h => h_no (Or.inl h)
      have h_tail : ¬ hasHonestOverlap rest := fun h => h_no (Or.inr h)
      have h_ih := ih h_tail
      simp only [countQ1, countQ2, countByz, List.length_cons]
      cases hb : r.isByz <;> cases h1 : r.inQ1 <;> cases h2 : r.inQ2
      all_goals simp_all
      all_goals try omega

theorem bft_quorum_intersection_honest
    (recs : List ValidatorVote)
    (h_byz : 3 * countByz recs < recs.length)
    (h_q1  : 2 * recs.length < 3 * countQ1 recs)
    (h_q2  : 2 * recs.length < 3 * countQ2 recs) :
    hasHonestOverlap recs := by
  by_cases h : hasHonestOverlap recs
  · exact h
  · have hbound := count_bound_of_no_overlap recs h
    omega

private theorem agreement_of_overlap (recs : List ValidatorVote) (v1 v2 : Nat)
    (hov : hasHonestOverlap recs) (h_hon : honestVotesConsistent v1 v2 recs) :
    v1 = v2 := by
  induction recs with
  | nil =>
      cases hov
  | cons r rest ih =>
      rcases h_hon with ⟨h_r, h_rest⟩
      rcases hov with h_hit | h_tail
      · exact h_r h_hit
      · exact ih h_tail h_rest

theorem bft_agreement_safety
    (recs : List ValidatorVote) (v1 v2 : Nat)
    (h_byz : 3 * countByz recs < recs.length)
    (h_q1  : 2 * recs.length < 3 * countQ1 recs)
    (h_q2  : 2 * recs.length < 3 * countQ2 recs)
    (h_hon : honestVotesConsistent v1 v2 recs) :
    v1 = v2 :=
  agreement_of_overlap recs v1 v2 (bft_quorum_intersection_honest recs h_byz h_q1 h_q2) h_hon

theorem merkle_verify_sound
    (H : Nat → Nat → Nat) (h_cr : CollisionResistant H)
    (pf : MerkleProof) (x y : Nat)
    (heq : verifyMerkle H x pf = verifyMerkle H y pf) :
    x = y := by
  induction pf generalizing x y with
  | nil =>
      exact heq
  | cons step rest ih =>
      rcases step with ⟨side, sib⟩
      cases side with
      | left =>
          simp only [verifyMerkle] at heq
          have hstep := ih (H x sib) (H y sib) heq
          exact (h_cr x sib y sib hstep).1
      | right =>
          simp only [verifyMerkle] at heq
          have hstep := ih (H sib x) (H sib y) heq
          exact (h_cr sib x sib y hstep).2

private theorem verifyMerkle_append
    (H : Nat → Nat → Nat) (acc : Nat) (p1 p2 : MerkleProof) :
    verifyMerkle H acc (p1 ++ p2) = verifyMerkle H (verifyMerkle H acc p1) p2 := by
  induction p1 generalizing acc with
  | nil => rfl
  | cons step rest ih =>
      rcases step with ⟨side, sib⟩
      cases side <;> simp only [List.cons_append, verifyMerkle, ih]

theorem merkle_build_complete
    (H : Nat → Nat → Nat) (t : MerkleTree) (dirs : List Side) (v : Nat) (pf : MerkleProof)
    (h_build : buildMerkleProof H t dirs = some (v, pf)) :
    verifyMerkle H v pf = merkleRoot H t := by
  induction dirs generalizing t v pf with
  | nil =>
      cases t with
      | leaf val =>
          simp only [buildMerkleProof] at h_build
          injection h_build with hpair
          injection hpair with hv hpf
          subst hv; subst hpf
          rfl
      | node _ _ =>
          simp only [buildMerkleProof] at h_build
          cases h_build
  | cons d rest ih =>
      cases t with
      | leaf _ =>
          cases d <;> simp only [buildMerkleProof] at h_build <;> cases h_build
      | node l r =>
          cases d with
          | left =>
              simp only [buildMerkleProof] at h_build
              cases hsub : buildMerkleProof H l rest with
              | none =>
                  simp only [hsub] at h_build
                  cases h_build
              | some pair =>
                  rcases pair with ⟨v0, pf0⟩
                  simp only [hsub] at h_build
                  injection h_build with hpair
                  injection hpair with hv hpf
                  subst hv; subst hpf
                  rw [verifyMerkle_append, ih l v0 pf0 hsub]
                  rfl
          | right =>
              simp only [buildMerkleProof] at h_build
              cases hsub : buildMerkleProof H r rest with
              | none =>
                  simp only [hsub] at h_build
                  cases h_build
              | some pair =>
                  rcases pair with ⟨v0, pf0⟩
                  simp only [hsub] at h_build
                  injection h_build with hpair
                  injection hpair with hv hpf
                  subst hv; subst hpf
                  rw [verifyMerkle_append, ih r v0 pf0 hsub]
                  rfl

theorem bft_spec_nonvacuous :
    let n0 : ValidatorVote := { isByz := true,  inQ1 := true,  inQ2 := true,  vote1 := some 1, vote2 := some 2 }
    let n1 : ValidatorVote := { isByz := false, inQ1 := true,  inQ2 := false, vote1 := some 1, vote2 := none }
    let n2 : ValidatorVote := { isByz := false, inQ1 := true,  inQ2 := true,  vote1 := some 1, vote2 := some 1 }
    let n3 : ValidatorVote := { isByz := false, inQ1 := false, inQ2 := true,  vote1 := none,   vote2 := some 1 }
    let cluster := [n0, n1, n2, n3]
    let tree := MerkleTree.node (MerkleTree.node (.leaf 11) (.leaf 22)) (MerkleTree.node (.leaf 33) (.leaf 44))
    3 * countByz cluster < cluster.length ∧
    2 * cluster.length < 3 * countQ1 cluster ∧
    2 * cluster.length < 3 * countQ2 cluster ∧
    (match buildMerkleProof demoHash tree [Side.left, Side.right] with
     | some (v, pf) => v = 22 ∧ verifyMerkle demoHash v pf = merkleRoot demoHash tree
     | none => False) := by
  refine ⟨by decide, by decide, by decide, ?_⟩
  exact ⟨rfl, rfl⟩

end Solution
