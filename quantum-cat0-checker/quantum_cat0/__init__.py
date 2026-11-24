"""Quantum-Network Entanglement Capacity & CAT(0) Feasibility Checker (Theorem C.1 + Strassen Duality)."""

__version__ = "0.1.0"

from .models import GHZResource, QuantumNetwork, get_topology, list_topologies
from .cat0_cone import MetricAuditResult, audit_metric_cat0, project_onto_cat0_socp, project_onto_euclidean_sdp
from .solvers import (
    CoveringCapacityResult,
    SLOCCFeasibilityResult,
    check_slocc_feasibility,
    solve_covering_capacity_hierarchy,
)

__all__ = [
    "GHZResource",
    "QuantumNetwork",
    "MetricAuditResult",
    "CoveringCapacityResult",
    "SLOCCFeasibilityResult",
    "get_topology",
    "list_topologies",
    "audit_metric_cat0",
    "project_onto_cat0_socp",
    "project_onto_euclidean_sdp",
    "solve_covering_capacity_hierarchy",
    "check_slocc_feasibility",
]
