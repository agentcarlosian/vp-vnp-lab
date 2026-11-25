import Specs.OrderBook.Statement

/-
  Blueprint 07 — Human-Audited TCB Target Theorems (`Challenge.lean`)
  Exchange matching, settlement conservation, and cross-margin liquidation invariants.
-/

namespace Challenge
open OrderBook

/-- 1. Limit-Price Improvement Guarantee: any non-zero fill respects BOTH maker ask limit
       and taker bid limit (`ask.price ≤ execPrice ≤ bid.price`). -/
theorem match_respects_limit_prices
    (bid ask : Order) (curSeq : Nat)
    (h_fill : 0 < (matchBidAsk bid ask curSeq).fillQty) :
    let m := matchBidAsk bid ask curSeq
    ask.price ≤ m.execPrice ∧ m.execPrice ≤ bid.price := by
  sorry

/-- 2. Exact Order-Quantity Conservation (no phantom over-fills or lost base units):
       `fillQty + remBidQty = bid.qty` and `fillQty + remAskQty = ask.qty`. -/
theorem match_conserves_order_quantities
    (bid ask : Order) (curSeq : Nat) :
    let m := matchBidAsk bid ask curSeq
    m.fillQty + m.remBidQty = bid.qty ∧ m.fillQty + m.remAskQty = ask.qty := by
  sorry

/-- 3. Atomic Quote-Currency & Fee Conservation: settling notional + protocol fee strictly
       conserves `totalQuote` across buyer, seller, and fee vault. -/
theorem settlement_conserves_total_quote
    (b : QuoteBalances) (notional fee : Nat) :
    totalQuote (settleQuote b notional fee).2 = totalQuote b := by
  sorry

/-- 4. Exact Integer Margin Liquidation Characterization: triggers iff `10000 * collateral < maintBps * notional`. -/
theorem margin_liquidation_exact_iff
    (collateral notional maintBps : Nat) :
    isLiquidatable collateral notional maintBps = true ↔
    10000 * collateral < maintBps * notional := by
  sorry

/-- 5. Strict Sequence Monotonicity: matching strictly advances the exchange event sequence. -/
theorem orderbook_seq_strictly_increasing
    (bid ask : Order) (curSeq : Nat) :
    curSeq < (matchBidAsk bid ask curSeq).nextSeq := by
  sorry

/-- 6. Mandatory non-vacuity witness: partial fill (`bid 105 @ 10` vs `ask 100 @ 6` -> `fill 6 @ 100`),
       quote settlement with fee, and healthy vs. underwater margin checks. -/
theorem orderbook_spec_nonvacuous :
    let bid : Order := { id := 1, seq := 10, price := 105, qty := 10 }
    let ask : Order := { id := 2, seq := 9,  price := 100, qty := 6 }
    let m := matchBidAsk bid ask 50
    let b0 : QuoteBalances := { buyerQuote := 2000, sellerQuote := 500, feeVault := 0 }
    let (settled, b1) := settleQuote b0 (m.fillQty * m.execPrice) 3
    m.fillQty = 6 ∧ m.execPrice = 100 ∧ m.remBidQty = 4 ∧ m.remAskQty = 0 ∧
    settled = true ∧ totalQuote b1 = 2500 ∧ b1.feeVault = 3 ∧
    isLiquidatable 49 1000 500 = true ∧
    isLiquidatable 50 1000 500 = false := by
  sorry

end Challenge
