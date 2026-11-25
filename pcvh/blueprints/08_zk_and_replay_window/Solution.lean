import Specs.ZkReplay.Statement

/-
  Blueprint 08 — Verified Zero-Knowledge Gadgets & Sliding-Window Anti-Replay Proofs (`Solution.lean`)
  Zero `sorry`, zero custom axioms, zero Mathlib dependency.
-/

namespace Solution
open ZkReplay

theorem zk_bool_wire_sound (b : Int) (h : isBoolWire b) :
    b = 0 ∨ b = 1 := by
  unfold isBoolWire at h
  by_cases hb0 : b ≤ 0
  · by_cases hzero : b = 0
    · exact Or.inl hzero
    · have hneg1 : 0 < -b := by omega
      have hneg2 : 0 < 1 - b := by omega
      have hpos : 0 < (-b) * (1 - b) := Int.mul_pos hneg1 hneg2
      have heq : (-b) * (1 - b) = b * (b - 1) := by
        have hsub : 1 - b = -(b - 1) := by omega
        rw [hsub, Int.neg_mul_neg]
      omega
  · by_cases hone : b = 1
    · exact Or.inr hone
    · have hp1 : 0 < b := by omega
      have hp2 : 0 < b - 1 := by omega
      have hpos : 0 < b * (b - 1) := Int.mul_pos hp1 hp2
      omega

theorem zk_range4_sound
    (b0 b1 b2 b3 : Int)
    (h0 : isBoolWire b0) (h1 : isBoolWire b1)
    (h2 : isBoolWire b2) (h3 : isBoolWire b3) :
    0 ≤ packBits4 b0 b1 b2 b3 ∧ packBits4 b0 b1 b2 b3 < 16 := by
  rcases zk_bool_wire_sound b0 h0 with rfl | rfl <;>
  rcases zk_bool_wire_sound b1 h1 with rfl | rfl <;>
  rcases zk_bool_wire_sound b2 h2 with rfl | rfl <;>
  rcases zk_bool_wire_sound b3 h3 with rfl | rfl <;>
  unfold packBits4 <;> omega

theorem zk_range4_complete (v : Nat) (hv : v < 16) :
    let (b0, b1, b2, b3) := unpackBits4 v
    isBoolWire b0 ∧ isBoolWire b1 ∧ isBoolWire b2 ∧ isBoolWire b3 ∧
    packBits4 b0 b1 b2 b3 = Int.ofNat v := by
  have hcases :
      v = 0 ∨ v = 1 ∨ v = 2 ∨ v = 3 ∨ v = 4 ∨ v = 5 ∨ v = 6 ∨ v = 7 ∨
      v = 8 ∨ v = 9 ∨ v = 10 ∨ v = 11 ∨ v = 12 ∨ v = 13 ∨ v = 14 ∨ v = 15 := by omega
  rcases hcases with rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl |
                     rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl <;>
  unfold unpackBits4 isBoolWire packBits4 <;> decide

theorem zk_mux_sound (s a b : Int) (hs : isBoolWire s) :
    (s = 0 → muxGate s a b = b) ∧ (s = 1 → muxGate s a b = a) := by
  unfold muxGate
  constructor
  · intro h0; subst h0; simp
  · intro h1; subst h1; simp

theorem replay_immediate_duplicate_rejected
    (w0 w1 : ReplayWindow) (seq : Nat)
    (h_acc : acceptPacket w0 seq = (true, w1)) :
    (acceptPacket w1 seq).1 = false := by
  unfold acceptPacket at h_acc
  dsimp only at h_acc
  split at h_acc
  · injection h_acc with _ hw1
    subst hw1
    unfold acceptPacket
    dsimp only
    simp [windowSize]
  · split at h_acc
    · injection h_acc with _ hw1
      subst hw1
      unfold acceptPacket
      dsimp only
      simp [windowSize]
    · split at h_acc
      · simp at h_acc
      · split at h_acc
        · simp at h_acc
        · rename_i hinit hnotgt hlt64 hnotmem
          injection h_acc with _ hw1
          subst hw1
          unfold acceptPacket
          dsimp only
          simp [hnotgt, hlt64]

theorem replay_stale_outside_window_rejected
    (w : ReplayWindow) (seq : Nat)
    (h_init : w.initialized = true)
    (h_stale : seq + windowSize ≤ w.highest) :
    acceptPacket w seq = (false, w) := by
  unfold acceptPacket windowSize at *
  dsimp only
  have hnotgt : ¬ w.highest < seq := by omega
  have hge64 : 64 ≤ w.highest - seq := by omega
  simp [h_init, hnotgt, hge64]

theorem replay_highest_monotone (w : ReplayWindow) (seq : Nat)
    (h_wf : w.initialized = true ∨ w.highest = 0) :
    w.highest ≤ (acceptPacket w seq).2.highest := by
  unfold acceptPacket
  dsimp only
  split
  · rename_i hnotinit
    rcases h_wf with hinit | hzero
    · simp [hinit] at hnotinit
    · simp [hzero]
  · split
    · simp; omega
    · split
      · simp
      · split <;> simp

theorem zk_replay_spec_nonvacuous :
    let (b0, b1, b2, b3) := unpackBits4 13
    let (ok1, w1) := acceptPacket emptyWindow 100
    let (ok2, w2) := acceptPacket w1 97
    let (okDup, w3) := acceptPacket w2 97
    let (okStale, _) := acceptPacket w3 20
    (b0, b1, b2, b3) = (1, 0, 1, 1) ∧
    packBits4 b0 b1 b2 b3 = 13 ∧
    ok1 = true ∧ ok2 = true ∧ okDup = false ∧ okStale = false := by
  decide

end Solution
