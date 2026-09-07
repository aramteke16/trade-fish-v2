"""Indian cash-equity delivery cost model (plan §Phase 0). Rates from settings.yaml."""

from tradefish import config


def round_trip_cost(buy_value: float, sell_value: float | None = None) -> float:
    """Total charges in rupees for one buy + one sell of the given notional."""
    if sell_value is None:
        sell_value = buy_value
    c = config.costs()

    brokerage = 2 * c["brokerage_per_order_rs"]
    stt = buy_value * c["stt_buy"] + sell_value * c["stt_sell"]
    exchange = (buy_value + sell_value) * c["exchange_txn"]
    sebi = (buy_value + sell_value) * c["sebi_rs_per_crore"] / 1e7
    stamp = buy_value * c["stamp_buy"]
    gst = c["gst"] * (brokerage + exchange + sebi)
    dp = c["dp_charge_rs"]

    return brokerage + stt + exchange + sebi + stamp + gst + dp


def side_cost(value: float, side: str) -> float:
    """Charges in rupees for a single buy or sell of the given notional."""
    c = config.costs()
    brokerage = c["brokerage_per_order_rs"]
    stt = value * (c["stt_buy"] if side == "buy" else c["stt_sell"])
    exchange = value * c["exchange_txn"]
    sebi = value * c["sebi_rs_per_crore"] / 1e7
    stamp = value * c["stamp_buy"] if side == "buy" else 0.0
    gst = c["gst"] * (brokerage + exchange + sebi)
    dp = c["dp_charge_rs"] if side == "sell" else 0.0
    return brokerage + stt + exchange + sebi + stamp + gst + dp


def round_trip_pct(notional: float) -> float:
    """Round-trip cost as a fraction of notional. ~0.0022 for typical sizes."""
    return round_trip_cost(notional) / notional
