"""Production Python IR Peephole Optimizer (reference target for Blueprint 3)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Union


@dataclass(frozen=True)
class Const:
    v: int


@dataclass(frozen=True)
class Var:
    reg: int


@dataclass(frozen=True)
class BinOp:
    op: str  # "add" | "sub" | "mul"
    a: "Expr"
    b: "Expr"


Expr = Union[Const, Var, BinOp]


def eval_expr(env: Dict[int, int], e: Expr) -> int:
    if isinstance(e, Const):
        return e.v
    if isinstance(e, Var):
        return env.get(e.reg, 0)
    va, vb = eval_expr(env, e.a), eval_expr(env, e.b)
    if e.op == "add":
        return va + vb
    if e.op == "sub":
        return va - vb
    return va * vb


def expr_size(e: Expr) -> int:
    if isinstance(e, (Const, Var)):
        return 1
    return 1 + expr_size(e.a) + expr_size(e.b)


def simp_add(a: Expr, b: Expr) -> Expr:
    if isinstance(a, Const) and isinstance(b, Const):
        return Const(a.v + b.v)
    if isinstance(a, Const) and a.v == 0:
        return b
    if isinstance(b, Const) and b.v == 0:
        return a
    return BinOp("add", a, b)


def simp_sub(a: Expr, b: Expr) -> Expr:
    if isinstance(a, Const) and isinstance(b, Const):
        return Const(a.v - b.v)
    if isinstance(b, Const) and b.v == 0:
        return a
    if a == b:
        return Const(0)
    return BinOp("sub", a, b)


def simp_mul(a: Expr, b: Expr) -> Expr:
    if isinstance(a, Const) and isinstance(b, Const):
        return Const(a.v * b.v)
    if (isinstance(a, Const) and a.v == 0) or (isinstance(b, Const) and b.v == 0):
        return Const(0)
    if isinstance(a, Const) and a.v == 1:
        return b
    if isinstance(b, Const) and b.v == 1:
        return a
    return BinOp("mul", a, b)


def opt_pass(e: Expr) -> Expr:
    if isinstance(e, (Const, Var)):
        return e
    oa, ob = opt_pass(e.a), opt_pass(e.b)
    if e.op == "add":
        return simp_add(oa, ob)
    if e.op == "sub":
        return simp_sub(oa, ob)
    return simp_mul(oa, ob)
