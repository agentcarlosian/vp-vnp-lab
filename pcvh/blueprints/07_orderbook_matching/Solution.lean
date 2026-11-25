import Specs.OrderBook.Statement

/-
  Blueprint 07 — Verified Limit Order Book & Margin Proofs (`Solution.lean`)
  Zero `sorry`, zero custom axioms, zero Mathlib dependency.
-/

namespace Solution
open OrderBook

theorem match_respects_limit_prices
    (bid ask : Order) (curSeq : Nat)
    (h_fill : 0 < (matchBidAsk bid ask curSeq).fillQty) :
    let m := matchBidAsk bid ask curSeq
    ask.price ≤ m.execPrice ∧ m.execPrice ≤ bid.price := by
  dsimp only
  unfold matchBidAsk at h_fill ⊢
  dsimp only at h_fill ⊢
  split at h_fill
  · rename_i hcond
    simp [hcond]
  · simp at h_fill

theorem match_conserves_order_quantities
    (bid ask : Order) (curSeq : Nat) :
    let m := matchBidAsk bid ask curSeq
    m.fillQty + m.remBidQty = bid.qty ∧ m.fillQty + m.remAskQty = ask.qty := by
  dsimp only
  unfold matchBidAsk
  dsimp only
  split <;> simp <;> omega

theorem settlement_conserves_total_quote
    (b : QuoteBalances) (notional fee : Nat) :
    totalQuote (settleQuote b notional fee).2 = totalQuote b := by
  unfold settleQuote totalQuote
  split <;> simp <;> omega

theorem margin_liquidation_exact_iff
    (collateral notional maintBps : Nat) :
    isLiquidatable collateral notional maintBps = true ↔
    10000 * collateral < maintBps * notional := by
  unfold isLiquidatable
  simp

theorem orderbook_seq_strictly_increasing
    (bid ask : Order) (curSeq : Nat) :
    curSeq < (matchBidAsk bid ask curSeq).nextSeq := by
  unfold matchBidAsk
  dsimp only
  split <;> simp <;> omega

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
  decide

end Solution
