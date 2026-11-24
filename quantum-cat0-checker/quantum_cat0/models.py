"""Data models and canonical multi-party quantum network topologies."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import pathlib
from typing import Dict, List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class GHZResource:
    """Multi-party GHZ resource <2^rate>_{GHZ(parties)}."""
    parties: Tuple[int, ...]
    rate: float = 1.0


@dataclass
class QuantumNetwork:
    """Multi-party quantum network conversion instance: source EPR/GHZ resources -> target EPR demands."""
    name: str
    num_parties: int
    source_eprs: Dict[Tuple[int, int], float]  # undirected canonical (u < v) -> ebit capacity s_e
    target_eprs: Dict[Tuple[int, int], float]  # undirected canonical (u < v) -> target ebit rate t_e
    source_ghz: List[GHZResource] = field(default_factory=list)
    party_labels: Optional[List[str]] = None
    description: str = ""

    def __post_init__(self) -> None:
        self.source_eprs = _canon_edges(self.source_eprs, self.num_parties)
        self.target_eprs = _canon_edges(self.target_eprs, self.num_parties)
        if self.party_labels is None:
            self.party_labels = [f"P{i}" for i in range(self.num_parties)]
        elif len(self.party_labels) != self.num_parties:
            raise ValueError("party_labels length must equal num_parties")

    @property
    def total_source_ebits(self) -> float:
        return sum(self.source_eprs.values()) + sum(g.rate for g in self.source_ghz)

    @property
    def total_target_ebits(self) -> float:
        return sum(self.target_eprs.values())

    def to_dict(self) -> Dict[str, object]:
        return {
            "name": self.name,
            "num_parties": self.num_parties,
            "party_labels": self.party_labels,
            "description": self.description,
            "source_eprs": [[u, v, w] for (u, v), w in sorted(self.source_eprs.items())],
            "target_eprs": [[u, v, w] for (u, v), w in sorted(self.target_eprs.items())],
            "source_ghz": [{"parties": list(g.parties), "rate": g.rate} for g in self.source_ghz],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "QuantumNetwork":
        n = int(data["num_parties"])
        src = {(int(u), int(v)): float(w) for u, v, w in data.get("source_eprs", [])}
        tgt = {(int(u), int(v)): float(w) for u, v, w in data.get("target_eprs", [])}
        ghz = [
            GHZResource(parties=tuple(sorted(set(int(p) for p in g["parties"]))), rate=float(g.get("rate", 1.0)))
            for g in data.get("source_ghz", [])
        ]
        labels = data.get("party_labels")
        return cls(
            name=str(data.get("name", "custom")),
            num_parties=n,
            source_eprs=src,
            target_eprs=tgt,
            source_ghz=ghz,
            party_labels=list(labels) if labels else None,
            description=str(data.get("description", "")),
        )

    @classmethod
    def from_json_file(cls, path: pathlib.Path) -> "QuantumNetwork":
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _canon_edges(edges: Dict[Tuple[int, int], float], n: int) -> Dict[Tuple[int, int], float]:
    out: Dict[Tuple[int, int], float] = {}
    for (u, v), w in edges.items():
        if u == v or w <= 0:
            continue
        if not (0 <= u < n and 0 <= v < n):
            raise ValueError(f"Edge ({u}, {v}) out of range for {n} parties")
        key = (u, v) if u < v else (v, u)
        out[key] = out.get(key, 0.0) + float(w)
    return out


def _grid_network(rows: int, cols: int, name: str, desc: str) -> QuantumNetwork:
    def idx(r: int, c: int) -> int:
        return r * cols + c

    n = rows * cols
    src: Dict[Tuple[int, int], float] = {}
    for r in range(rows):
        for c in range(cols):
            if r + 1 < rows:
                src[(idx(r, c), idx(r + 1, c))] = 1.0
            if c + 1 < cols:
                src[(idx(r, c), idx(r, c + 1))] = 1.0
    # Cross-corner long-range diagonal EPR demands
    tgt = {
        (idx(0, 0), idx(rows - 1, cols - 1)): 1.0,
        (idx(0, cols - 1), idx(rows - 1, 0)): 1.0,
    }
    labels = [f"({r},{c})" for r in range(rows) for c in range(cols)]
    return QuantumNetwork(name=name, num_parties=n, source_eprs=src, target_eprs=tgt, party_labels=labels, description=desc)


def _hypercube_q3() -> QuantumNetwork:
    # 8 vertices 0..7; edges connect vertices differing in 1 bit; targets are 4 antipodal body diagonals (v, v^7)
    src: Dict[Tuple[int, int], float] = {}
    for v in range(8):
        for b in (1, 2, 4):
            u = v ^ b
            if v < u:
                src[(v, u)] = 1.0
    tgt = {(v, v ^ 7): 1.0 for v in range(4)}
    labels = [f"{v:03b}" for v in range(8)]
    return QuantumNetwork(
        name="hypercube_Q3",
        num_parties=8,
        source_eprs=src,
        target_eprs=tgt,
        party_labels=labels,
        description="3D quantum repeater cube Q_3 routing all 4 antipodal body diagonals (CAT(0) gives sqrt(3)x Enflo compression!).",
    )


def _butterfly_6() -> QuantumNetwork:
    # Classic 6-node quantum butterfly network:
    # S1=0, S2=1, R1=2 (bottleneck top), R2=3 (bottleneck bottom), T1=4 (wants S2), T2=5 (wants S1)
    src = {
        (0, 2): 1.0,
        (1, 2): 1.0,
        (2, 3): 1.0,
        (3, 4): 1.0,
        (3, 5): 1.0,
        (0, 4): 1.0,
        (1, 5): 1.0,
    }
    tgt = {(0, 5): 1.0, (1, 4): 1.0}
    return QuantumNetwork(
        name="butterfly_6",
        num_parties=6,
        source_eprs=src,
        target_eprs=tgt,
        party_labels=["S1", "S2", "R1", "R2", "T1", "T2"],
        description="6-node quantum butterfly network routing crossing pairs (S1,T2) and (S2,T1) through a shared repeater bottleneck.",
    )


def _petersen_10() -> QuantumNetwork:
    # Outer 5-cycle 0-1-2-3-4, inner 5-star 5-7-9-6-8, spokes i-(i+5)
    src: Dict[Tuple[int, int], float] = {}
    for i in range(5):
        src[(i, (i + 1) % 5)] = 1.0
        src[(i, i + 5)] = 1.0
        src[(5 + i, 5 + (i + 2) % 5)] = 1.0
    # 5 antipodal / distance-2 pairs across outer & inner rings
    tgt = {(0, 2): 1.0, (1, 3): 1.0, (2, 4): 1.0, (3, 0): 1.0, (4, 1): 1.0}
    return QuantumNetwork(
        name="petersen_10",
        num_parties=10,
        source_eprs=src,
        target_eprs=tgt,
        party_labels=[f"O{i}" for i in range(5)] + [f"I{i}" for i in range(5)],
        description="10-node Petersen quantum network routing the 5-cycle of distance-2 outer chords.",
    )


def _build_topologies() -> Dict[str, QuantumNetwork]:
    return {
        "C4_crossing": QuantumNetwork(
            name="C4_crossing",
            num_parties=4,
            source_eprs={(0, 1): 1.0, (1, 2): 1.0, (2, 3): 1.0, (3, 0): 1.0},
            target_eprs={(0, 2): 1.0, (1, 3): 1.0},
            party_labels=["x", "y", "v", "u"],
            description="4-cycle C_4 routing two crossing EPR diagonals (exact sqrt(2)x CAT(0) covering compression over triangle bound).",
        ),
        "C4_infeasible_single": QuantumNetwork(
            name="C4_infeasible_single",
            num_parties=4,
            source_eprs={(0, 1): 0.75, (1, 2): 0.75, (2, 3): 0.75, (3, 0): 0.75},
            target_eprs={(0, 2): 1.0, (1, 3): 1.0},
            party_labels=["x", "y", "v", "u"],
            description="Symmetric 0.75-ebit 4-cycle attempting 2 crossing EPR pairs: violates bipartition cut (1.5 < 2.0) for single restriction, yet feasible via L2 cover!",
        ),
        "K3_triangle": QuantumNetwork(
            name="K3_triangle",
            num_parties=3,
            source_eprs={(0, 1): 1.0, (1, 2): 1.0},
            target_eprs={(0, 2): 1.0},
            party_labels=["A", "B", "C"],
            description="3-party entanglement swapping chain (all 3-point metrics embed in R^2, so CAT(0) = Metric with zero gap).",
        ),
        "butterfly_6": _butterfly_6(),
        "hypercube_Q3": _hypercube_q3(),
        "grid_2x3": _grid_network(2, 3, "grid_2x3", "2x3 planar quantum repeater lattice routing long-range crossing diagonals."),
        "grid_3x3": _grid_network(3, 3, "grid_3x3", "3x3 planar quantum repeater lattice routing corner-to-corner crossing diagonals."),
        "K23_bipartite": QuantumNetwork(
            name="K23_bipartite",
            num_parties=5,
            source_eprs={(0, 2): 1.0, (0, 3): 1.0, (0, 4): 1.0, (1, 2): 1.0, (1, 3): 1.0, (1, 4): 1.0},
            target_eprs={(0, 1): 1.0, (2, 3): 1.0, (3, 4): 1.0, (2, 4): 1.0},
            party_labels=["A0", "A1", "B0", "B1", "B2"],
            description="Complete bipartite K_{2,3} repeater network routing same-side pairs (separates non-Euclidean CAT(0) vs Euclidean!).",
        ),
        "wheel_W5": QuantumNetwork(
            name="wheel_W5",
            num_parties=6,
            source_eprs={
                (0, 1): 1.0, (0, 2): 1.0, (0, 3): 1.0, (0, 4): 1.0, (0, 5): 1.0,
                (1, 2): 0.5, (2, 3): 0.5, (3, 4): 0.5, (4, 5): 0.5, (5, 1): 0.5,
            },
            target_eprs={(1, 3): 1.0, (2, 4): 1.0, (3, 5): 1.0, (4, 1): 1.0, (5, 2): 1.0},
            party_labels=["Hub", "R1", "R2", "R3", "R4", "R5"],
            description="5-spoke quantum repeater wheel with central hub and rim links routing rim chords.",
        ),
        "petersen_10": _petersen_10(),
        "ghz4_hybrid": QuantumNetwork(
            name="ghz4_hybrid",
            num_parties=4,
            source_eprs={(0, 1): 0.5, (2, 3): 0.5},
            target_eprs={(0, 2): 1.0, (1, 3): 1.0},
            source_ghz=[GHZResource(parties=(0, 1, 2, 3), rate=1.5)],
            party_labels=["A", "B", "C", "D"],
            description="4-party hybrid GHZ + EPR network attempting to distill two crossing EPR pairs.",
        ),
    }


TOPOLOGIES = _build_topologies()


def list_topologies() -> List[str]:
    return sorted(TOPOLOGIES.keys())


def get_topology(name: str) -> QuantumNetwork:
    if name not in TOPOLOGIES:
        raise KeyError(f"Unknown topology {name!r}. Available: {', '.join(list_topologies())}")
    return TOPOLOGIES[name]
