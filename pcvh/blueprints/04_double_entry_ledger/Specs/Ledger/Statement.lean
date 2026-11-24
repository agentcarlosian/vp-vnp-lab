/-
  Blueprint 4 — Human-Audited TCB Specification (`Statement.lean`)
  Double-Entry Idempotent Payment Ledger with Platform Fees & Overdraft Protection
-/

namespace Ledger

/-- Account balances represented as `(accountId, signedBalance)` entries. -/
abbrev Balances := List (Nat × Int)

/-- Lookup balance for `acct` (defaults to `0` for unseen accounts). -/
def lookupBalance : Balances → Nat → Int
  | [], _ => 0
  | (a, b) :: rest, k => if a == k then b else lookupBalance rest k

/-- Apply signed delta `d` to `acct` (in-place update on first match, else append). -/
def applyDelta : Balances → Nat → Int → Balances
  | [], k, d => [(k, d)]
  | (a, b) :: rest, k, d =>
      if a == k then (a, b + d) :: rest
      else (a, b) :: applyDelta rest k d

/-- Total conserved monetary value across all ledger accounts. -/
def totalBalance : Balances → Int
  | [] => 0
  | (_, b) :: rest => b + totalBalance rest

/-- Overdraft safety predicate: every recorded balance is non-negative. -/
def allNonNeg : Balances → Prop
  | [] => True
  | (_, b) :: rest => 0 ≤ b ∧ allNonNeg rest

structure LedgerState where
  balances : Balances
  seenKeys : List Nat
  deriving Repr, DecidableEq

structure TransferEvent where
  idKey : Nat
  fromAcct : Nat
  toAcct : Nat
  feeAcct : Nat
  amount : Nat
  fee : Nat
  deriving Repr, DecidableEq

inductive StepError
  | zeroAmount
  | insufficientFunds
  deriving Repr, DecidableEq

inductive StepResult
  | ok (next : LedgerState)
  | err (reason : StepError)
  deriving Repr, DecidableEq

/-- Total debit applied to `fromAcct`: principal + platform fee. -/
def debitTotal (ev : TransferEvent) : Int :=
  (ev.amount : Int) + (ev.fee : Int)

/-- Atomic double-entry payment step:
    1. Idempotent no-op if `ev.idKey` was already processed (Zero Double-Spend).
    2. Rejects zero-amount transfers.
    3. Rejects transfers exceeding `fromAcct`'s current balance (No Overdraft).
    4. Commits 3 balanced legs (`-amount-fee`, `+amount`, `+fee`) and records `idKey`. -/
def step (s : LedgerState) (ev : TransferEvent) : StepResult :=
  if ev.idKey ∈ s.seenKeys then
    StepResult.ok s
  else if ev.amount == 0 then
    StepResult.err StepError.zeroAmount
  else if lookupBalance s.balances ev.fromAcct < debitTotal ev then
    StepResult.err StepError.insufficientFunds
  else
    let b1 := applyDelta s.balances ev.fromAcct (-(debitTotal ev))
    let b2 := applyDelta b1 ev.toAcct (ev.amount : Int)
    let b3 := applyDelta b2 ev.feeAcct (ev.fee : Int)
    StepResult.ok { balances := b3, seenKeys := ev.idKey :: s.seenKeys }

/-- Execute an arbitrary event stream, safely ignoring rejected transactions. -/
def execTrace : LedgerState → List TransferEvent → LedgerState
  | s, [] => s
  | s, ev :: rest =>
      match step s ev with
      | StepResult.ok s' => execTrace s' rest
      | StepResult.err _ => execTrace s rest

end Ledger
