/-
  Blueprint 08 — Trusted Computing Base Specification (`Statement.lean`)
  Part A: R1CS / Plonkish Zero-Knowledge Circuit Gadgets (booleanity, 4-bit range decomposition, MUX)
  Part B: RFC-6479 / WireGuard 64-Packet Sliding-Window Anti-Replay State Machine
-/

namespace ZkReplay

/-! ### Part A: Zero-Knowledge Arithmetic Circuit Gadgets -/

/-- Standard R1CS booleanity constraint: `b * (b - 1) = 0`. -/
def isBoolWire (b : Int) : Prop :=
  b * (b - 1) = 0

/-- Linear bit-packing constraint for a 4-bit unsigned limb `[0, 15]`. -/
def packBits4 (b0 b1 b2 b3 : Int) : Int :=
  b0 + 2 * b1 + 4 * b2 + 8 * b3

/-- Witness generator decomposing `v : Nat` into 4 binary wires. -/
def unpackBits4 (v : Nat) : Int × Int × Int × Int :=
  ( Int.ofNat (v % 2),
    Int.ofNat ((v / 2) % 2),
    Int.ofNat ((v / 4) % 2),
    Int.ofNat ((v / 8) % 2) )

/-- Degree-2 conditional selector gadget `mux(s, a, b) = s * a + (1 - s) * b`. -/
def muxGate (s a b : Int) : Int :=
  s * a + (1 - s) * b

/-! ### Part B: 64-Packet Sliding-Window Anti-Replay State Machine -/

def windowSize : Nat := 64

structure ReplayWindow where
  initialized : Bool
  highest     : Nat
  /-- Offset `d < 64` is in `seenOffsets` iff sequence number `highest - d` was already accepted. -/
  seenOffsets : List Nat
  deriving Repr, DecidableEq

def emptyWindow : ReplayWindow :=
  { initialized := false, highest := 0, seenOffsets := [] }

/-- Evaluate and update the 64-packet anti-replay window upon receiving packet `seq`. -/
def acceptPacket (w : ReplayWindow) (seq : Nat) : Bool × ReplayWindow :=
  if !w.initialized then
    (true, { initialized := true, highest := seq, seenOffsets := [0] })
  else if w.highest < seq then
    let delta := seq - w.highest
    let shifted := 0 :: (w.seenOffsets.map (fun d => d + delta)).filter (fun d => d < windowSize)
    (true, { initialized := true, highest := seq, seenOffsets := shifted })
  else
    let offset := w.highest - seq
    if windowSize ≤ offset then
      (false, w)
    else if offset ∈ w.seenOffsets then
      (false, w)
    else
      (true, { initialized := true, highest := w.highest, seenOffsets := offset :: w.seenOffsets })

end ZkReplay
