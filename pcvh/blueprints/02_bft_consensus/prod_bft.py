"""Production Python BFT Quorum Validator & Merkle Tree (reference target for Blueprint 2)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Literal, Optional, Tuple


def demo_hash(a: int, b: int) -> int:
    return (a + b) * (a + b + 1) // 2 + b


@dataclass(frozen=True)
class ValidatorVote:
    is_byz: bool
    in_q1: bool
    in_q2: bool


def check_bft_quorums(votes: List[ValidatorVote]) -> Tuple[int, int, int, bool]:
    n = len(votes)
    f = sum(1 for v in votes if v.is_byz)
    q1 = sum(1 for v in votes if v.in_q1)
    q2 = sum(1 for v in votes if v.in_q2)
    overlap = any((not v.is_byz) and v.in_q1 and v.in_q2 for v in votes)
    if 3 * f < n and 2 * n < 3 * q1 and 2 * n < 3 * q2:
        assert overlap, "BFT quorum intersection theorem violated!"
    return f, q1, q2, overlap


@dataclass(frozen=True)
class MerkleNode:
    val: Optional[int] = None
    left: Optional["MerkleNode"] = None
    right: Optional["MerkleNode"] = None

    def root(self) -> int:
        if self.val is not None:
            return self.val
        assert self.left is not None and self.right is not None
        return demo_hash(self.left.root(), self.right.root())


def build_merkle_proof(node: MerkleNode, dirs: List[Literal["L", "R"]]) -> Tuple[int, List[Tuple[str, int]]]:
    if not dirs:
        assert node.val is not None
        return node.val, []
    assert node.left is not None and node.right is not None
    if dirs[0] == "L":
        v, pf = build_merkle_proof(node.left, dirs[1:])
        return v, pf + [("L", node.right.root())]
    v, pf = build_merkle_proof(node.right, dirs[1:])
    return v, pf + [("R", node.left.root())]


def verify_merkle_proof(leaf_val: int, proof: List[Tuple[str, int]]) -> int:
    acc = leaf_val
    for side, sib in proof:
        acc = demo_hash(acc, sib) if side == "L" else demo_hash(sib, acc)
    return acc
