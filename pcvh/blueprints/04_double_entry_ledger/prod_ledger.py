"""Production Python Double-Entry Idempotent Payment Ledger (reference target for Blueprint 4)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Literal, Set, Tuple


@dataclass(frozen=True)
class TransferEvent:
    id_key: int
    from_acct: int
    to_acct: int
    fee_acct: int
    amount: int
    fee: int


@dataclass
class DoubleEntryLedger:
    """Production double-entry payment engine with idempotency & overdraft protection."""

    balances: Dict[int, int] = field(default_factory=dict)
    seen_keys: Set[int] = field(default_factory=set)

    def balance_of(self, acct: int) -> int:
        return self.balances.get(acct, 0)

    def total_balance(self) -> int:
        return sum(self.balances.values())

    def apply(self, ev: TransferEvent) -> Tuple[Literal["ok", "err"], str]:
        if ev.id_key in self.seen_keys:
            return "ok", "idempotent_replay"
        if ev.amount <= 0:
            return "err", "zeroAmount"
        debit = ev.amount + ev.fee
        if self.balance_of(ev.from_acct) < debit:
            return "err", "insufficientFunds"

        # Three balanced double-entry legs (works even if accounts alias!)
        self.balances[ev.from_acct] = self.balance_of(ev.from_acct) - debit
        self.balances[ev.to_acct] = self.balance_of(ev.to_acct) + ev.amount
        self.balances[ev.fee_acct] = self.balance_of(ev.fee_acct) + ev.fee
        self.seen_keys.add(ev.id_key)
        return "ok", "committed"

    def exec_trace(self, events: List[TransferEvent]) -> None:
        for ev in events:
            self.apply(ev)
