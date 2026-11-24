import Specs.Bft.Statement

/-
  Blueprint 2 — Human-Audited TCB Target Theorems (`Challenge.lean`)
  BFT Agreement Safety (3f < n) + Collision-Resistant Merkle Tree Soundness & Completeness.
-/

namespace Challenge
open BftProto

/-- 1. BFT Quorum Intersection: with `3f < n` Byzantine faults and two `> 2n/3` quorums,
       there MUST exist at least one honest validator in both quorums. -/
theorem bft_quorum_intersection_honest
    (recs : List ValidatorVote)
    (h_byz : 3 * countByz recs < recs.length)
    (h_q1  : 2 * recs.length < 3 * countQ1 recs)
    (h_q2  : 2 * recs.length < 3 * countQ2 recs) :
    hasHonestOverlap recs := by
  sorry

/-- 2. BFT Agreement Safety: no two distinct blocks can both achieve valid QCs at the same height. -/
theorem bft_agreement_safety
    (recs : List ValidatorVote) (v1 v2 : Nat)
    (h_byz : 3 * countByz recs < recs.length)
    (h_q1  : 2 * recs.length < 3 * countQ1 recs)
    (h_q2  : 2 * recs.length < 3 * countQ2 recs)
    (h_hon : honestVotesConsistent v1 v2 recs) :
    v1 = v2 := by
  sorry

/-- 3. Merkle Proof Soundness: under collision-resistant `H`, two leaves sharing a valid proof path
       and yielding the same root MUST be equal. -/
theorem merkle_verify_sound
    (H : Nat → Nat → Nat) (h_cr : CollisionResistant H)
    (pf : MerkleProof) (x y : Nat)
    (heq : verifyMerkle H x pf = verifyMerkle H y pf) :
    x = y := by
  sorry

/-- 4. Merkle Inclusion Completeness: any proof extracted from a valid path verifies to `merkleRoot`. -/
theorem merkle_build_complete
    (H : Nat → Nat → Nat) (t : MerkleTree) (dirs : List Side) (v : Nat) (pf : MerkleProof)
    (h_build : buildMerkleProof H t dirs = some (v, pf)) :
    verifyMerkle H v pf = merkleRoot H t := by
  sorry

/-- 5. Mandatory non-vacuity witness: concrete 4-node BFT cluster (n=4, f=1) + 4-leaf Merkle proof. -/
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
  sorry

end Challenge
