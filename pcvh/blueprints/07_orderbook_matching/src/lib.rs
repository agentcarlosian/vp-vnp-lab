/// Production Rust Price-Time Priority Limit Order Book & Cross-Margin Engine (Blueprint 07)

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Order {
    pub id: u64,
    pub seq: u64,
    pub price: u64,
    pub qty: u64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct MatchOutcome {
    pub fill_qty: u64,
    pub exec_price: u64,
    pub rem_bid_qty: u64,
    pub rem_ask_qty: u64,
    pub next_seq: u64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct QuoteBalances {
    pub buyer_quote: u128,
    pub seller_quote: u128,
    pub fee_vault: u128,
}

pub fn match_bid_ask(bid: Order, ask: Order, cur_seq: u64) -> MatchOutcome {
    if ask.price <= bid.price && bid.qty > 0 && ask.qty > 0 {
        let fill = bid.qty.min(ask.qty);
        MatchOutcome {
            fill_qty: fill,
            exec_price: ask.price,
            rem_bid_qty: bid.qty - fill,
            rem_ask_qty: ask.qty - fill,
            next_seq: cur_seq + 1,
        }
    } else {
        MatchOutcome {
            fill_qty: 0,
            exec_price: ask.price,
            rem_bid_qty: bid.qty,
            rem_ask_qty: ask.qty,
            next_seq: cur_seq + 1,
        }
    }
}

pub fn settle_quote(b: QuoteBalances, notional: u128, fee: u128) -> (bool, QuoteBalances) {
    if notional + fee <= b.buyer_quote {
        (
            true,
            QuoteBalances {
                buyer_quote: b.buyer_quote - (notional + fee),
                seller_quote: b.seller_quote + notional,
                fee_vault: b.fee_vault + fee,
            },
        )
    } else {
        (false, b)
    }
}

pub fn is_liquidatable(collateral: u128, notional: u128, maint_bps: u128) -> bool {
    10_000u128 * collateral < maint_bps * notional
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_partial_fill_and_settlement() {
        let bid = Order { id: 1, seq: 10, price: 105, qty: 10 };
        let ask = Order { id: 2, seq: 9, price: 100, qty: 6 };
        let m = match_bid_ask(bid, ask, 50);
        assert_eq!(m.fill_qty, 6);
        assert_eq!(m.exec_price, 100);
        assert_eq!(m.rem_bid_qty, 4);
        assert_eq!(m.rem_ask_qty, 0);

        let b0 = QuoteBalances { buyer_quote: 2000, seller_quote: 500, fee_vault: 0 };
        let (ok, b1) = settle_quote(b0, (m.fill_qty * m.exec_price) as u128, 3);
        assert!(ok);
        assert_eq!(b1.buyer_quote + b1.seller_quote + b1.fee_vault, 2500);
        assert!(is_liquidatable(49, 1000, 500));
        assert!(!is_liquidatable(50, 1000, 500));
    }
}
