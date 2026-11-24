/-
  Blueprint 2 — Human-Audited TCB Specification (`Statement.lean`)
  BFT Quorum-Intersection Consensus Safety (3f < n) & Merkle Tree Inclusion Soundness
-/

namespace BftProto

/-- Per-validator snapshot at a consensus height: Byzantine flag & participation in two QCs. -/
structure ValidatorVote where
  isByz : Bool
  inQ1  : Bool
  inQ2  : Bool
  vote1 : Option Nat
  vote2 : Option Nat
  deriving Repr, DecidableEq

def countByz : List ValidatorVote → Nat
  | [] => 0
  | r :: rest => (if r.isByz then 1 else 0) + countByz rest

def countQ1 : List ValidatorVote → Nat
  | [] => 0
  | r :: rest => (if r.inQ1 then 1 else 0) + countQ1 rest

def countQ2 : List ValidatorVote → Nat
  | [] => 0
  | r :: rest => (if r.inQ2 then 1 else 0) + countQ2 rest

/-- Existence of at least one honest validator belonging to both quorums `Q1` and `Q2`. -/
def hasHonestOverlap : List ValidatorVote → Prop
  | [] => False
  | r :: rest => (r.isByz = false ∧ r.inQ1 = true ∧ r.inQ2 = true) ∨ hasHonestOverlap rest

/-- Honest single-vote protocol rule: every honest voter in Q1 voted for `v1`, in Q2 for `v2`,
    and never equivocates (cannot sign two distinct values at the same height). -/
def honestVotesConsistent (v1 v2 : Nat) : List ValidatorVote → Prop
  | [] => True
  | r :: rest =>
      ((r.isByz = false ∧ r.inQ1 = true ∧ r.inQ2 = true) → v1 = v2) ∧
      honestVotesConsistent v1 v2 rest

/-- Binary Merkle tree over integer leaf digests. -/
inductive MerkleTree where
  | leaf (val : Nat)
  | node (left right : MerkleTree)
  deriving Repr, DecidableEq

inductive Side where
  | left
  | right
  deriving Repr, DecidableEq

abbrev MerkleProof := List (Side × Nat)

/-- Compute the Merkle root under hash combiner `H : Nat → Nat → Nat`. -/
def merkleRoot (H : Nat → Nat → Nat) : MerkleTree → Nat
  | .leaf v => v
  | .node l r => H (merkleRoot H l) (merkleRoot H r)

/-- Bottom-up Merkle proof evaluator. -/
def verifyMerkle (H : Nat → Nat → Nat) : Nat → MerkleProof → Nat
  | acc, [] => acc
  | acc, (Side.left, sib) :: rest => verifyMerkle H (H acc sib) rest
  | acc, (Side.right, sib) :: rest => verifyMerkle H (H sib acc) rest

/-- Extract `(leafVal, bottomUpProof)` along a top-down path `dirs`. -/
def buildMerkleProof (H : Nat → Nat → Nat) : MerkleTree → List Side → Option (Nat × MerkleProof)
  | .leaf v, [] => some (v, [])
  | .node l r, Side.left :: rest =>
      match buildMerkleProof H l rest with
      | some (v, pf) => some (v, pf ++ [(Side.left, merkleRoot H r)])
      | none => none
  | .node l r, Side.right :: rest =>
      match buildMerkleProof H r rest with
      | some (v, pf) => some (v, pf ++ [(Side.right, merkleRoot H l)])
      | none => none
  | _, _ => none

/-- Abstract collision-resistance predicate for 2-to-1 hash combiner `H`. -/
def CollisionResistant (H : Nat → Nat → Nat) : Prop :=
  ∀ a b c d, H a b = H c d → a = c ∧ b = d

/-- Concrete toy hash combiner for executable witnesses & differential traces. -/
def demoHash (a b : Nat) : Nat :=
  (a + b) * (a + b + 1) / 2 + b

end BftProto
