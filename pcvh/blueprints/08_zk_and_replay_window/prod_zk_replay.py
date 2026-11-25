"""Production O(1) 64-Bit Bitmask Anti-Replay Window & ZK Witness Gadgets (Blueprint 08)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

MASK_64 = (1 << 64) - 1


def unpack_bits4(v: int) -> Tuple[int, int, int, int]:
    if not (0 <= v < 16):
        raise ValueError(f"4-bit range check failed: {v}")
    return (v & 1, (v >> 1) & 1, (v >> 2) & 1, (v >> 3) & 1)


def verify_r1cs_range4_and_mux(v: int, sel: int, a: int, b: int) -> Tuple[int, int]:
    b0, b1, b2, b3 = unpack_bits4(v)
    for bit in (b0, b1, b2, b3, sel):
        if bit * (bit - 1) != 0:
            raise ValueError("Booleanity R1CS constraint violated")
    packed = b0 + 2 * b1 + 4 * b2 + 8 * b3
    mux_out = sel * a + (1 - sel) * b
    return packed, mux_out


@dataclass
class WireGuardReplayWindow:
    """RFC-6479 / WireGuard O(1) 64-bit sliding bitmap anti-replay filter."""

    initialized: bool = False
    highest: int = 0
    bitmap: int = 0  # bit d (0..63) == 1 iff packet (highest - d) was seen

    def accept_packet(self, seq: int) -> bool:
        if not self.initialized:
            self.initialized = True
            self.highest = seq
            self.bitmap = 1
            return True

        if seq > self.highest:
            delta = seq - self.highest
            if delta >= 64:
                self.bitmap = 1
            else:
                self.bitmap = ((self.bitmap << delta) & MASK_64) | 1
            self.highest = seq
            return True

        offset = self.highest - seq
        if offset >= 64:
            return False
        bit = 1 << offset
        if self.bitmap & bit:
            return False
        self.bitmap |= bit
        return True
