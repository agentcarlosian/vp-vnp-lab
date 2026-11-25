use pcvh_blueprint07_orderbook::{is_liquidatable, match_bid_ask, settle_quote, Order, QuoteBalances};
use std::env;

fn lcg(state: &mut u64) -> u64 {
    *state = state.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
    *state >> 16
}

fn main() {
    let args: Vec<String> = env::args().collect();
    let traces: usize = args.get(1).and_then(|s| s.parse().ok()).unwrap_or(1000);
    let mut rng: u64 = args.get(2).and_then(|s| s.parse().ok()).unwrap_or(808);

    for i in 0..traces {
        let bid_p = (lcg(&mut rng) % 5_000) + 1;
        let ask_p = (lcg(&mut rng) % 5_000) + 1;
        let bid_q = lcg(&mut rng) % 200;
        let ask_q = lcg(&mut rng) % 200;
        let cur_seq = (i as u64) * 3 + (lcg(&mut rng) % 50);

        let bid = Order { id: 1, seq: cur_seq, price: bid_p, qty: bid_q };
        let ask = Order { id: 2, seq: cur_seq.saturating_sub(1), price: ask_p, qty: ask_q };
        let m = match_bid_ask(bid, ask, cur_seq);

        assert_eq!(m.fill_qty + m.rem_bid_qty, bid_q);
        assert_eq!(m.fill_qty + m.rem_ask_qty, ask_q);

        let buyer_q = (lcg(&mut rng) % 1_000_000) as u128;
        let seller_q = (lcg(&mut rng) % 1_000_000) as u128;
        let vault_q = (lcg(&mut rng) % 10_000) as u128;
        let notional = (m.fill_qty as u128) * (m.exec_price as u128);
        let fee = (lcg(&mut rng) % 500) as u128;

        let (settled, nb) = settle_quote(
            QuoteBalances { buyer_quote: buyer_q, seller_quote: seller_q, fee_vault: vault_q },
            notional,
            fee,
        );
        assert_eq!(nb.buyer_quote + nb.seller_quote + nb.fee_vault, buyer_q + seller_q + vault_q);

        let coll = (lcg(&mut rng) % 50_000) as u128;
        let pos_notional = ((lcg(&mut rng) % 500_000) + 1) as u128;
        let maint_bps = ((lcg(&mut rng) % 2_000) + 100) as u128;
        let liq = is_liquidatable(coll, pos_notional, maint_bps);

        println!(
            "{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}",
            bid_p, bid_q, ask_p, ask_q, cur_seq,
            m.fill_qty, m.exec_price, m.rem_bid_qty, m.rem_ask_qty, m.next_seq,
            buyer_q, seller_q, vault_q, notional, fee,
            if settled { 1 } else { 0 }, nb.buyer_quote, nb.seller_quote, nb.fee_vault,
            coll, pos_notional, maint_bps, if liq { 1 } else { 0 }
        );
    }
}
