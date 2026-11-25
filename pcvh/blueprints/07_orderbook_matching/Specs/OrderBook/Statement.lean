/-
  Blueprint 07 — Trusted Computing Base Specification (`Statement.lean`)
  Price-Time Priority Limit Order Book Matching, Quote Settlement & Margin Liquidation Engine.
-/

namespace OrderBook

structure Order where
  id    : Nat
  seq   : Nat
  price : Nat
  qty   : Nat
  deriving Repr, DecidableEq

structure MatchOutcome where
  fillQty   : Nat
  execPrice : Nat
  remBidQty : Nat
  remAskQty : Nat
  nextSeq   : Nat
  deriving Repr, DecidableEq

/-- Match an incoming aggressive buy `bid` against a resting maker `ask` at `ask.price`. -/
def matchBidAsk (bid ask : Order) (curSeq : Nat) : MatchOutcome :=
  if ask.price ≤ bid.price ∧ 0 < bid.qty ∧ 0 < ask.qty then
    let fill := min bid.qty ask.qty
    { fillQty   := fill,
      execPrice := ask.price,
      remBidQty := bid.qty - fill,
      remAskQty := ask.qty - fill,
      nextSeq   := curSeq + 1 }
  else
    { fillQty   := 0,
      execPrice := ask.price,
      remBidQty := bid.qty,
      remAskQty := ask.qty,
      nextSeq   := curSeq + 1 }

structure QuoteBalances where
  buyerQuote  : Nat
  sellerQuote : Nat
  feeVault    : Nat
  deriving Repr, DecidableEq

def totalQuote (b : QuoteBalances) : Nat :=
  b.buyerQuote + b.sellerQuote + b.feeVault

/-- Atomic quote-currency trade settlement with protocol fee routing. -/
def settleQuote (b : QuoteBalances) (notional fee : Nat) : Bool × QuoteBalances :=
  if notional + fee ≤ b.buyerQuote then
    (true, { buyerQuote  := b.buyerQuote - (notional + fee),
             sellerQuote := b.sellerQuote + notional,
             feeVault    := b.feeVault + fee })
  else
    (false, b)

/-- Exact integer cross-multiplied maintenance-margin liquidation check (zero float drift!). -/
def isLiquidatable (collateral notional maintBps : Nat) : Bool :=
  decide (10000 * collateral < maintBps * notional)

end OrderBook
