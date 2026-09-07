"""Week-by-week backtest loop. Calls the same rank/label/cost code the live jobs use."""

import pandas as pd

from tradefish import config, costs, metrics, strategy
from tradefish.labels.triple_barrier import label
from tradefish.model import baseline

from backtest import data as bt_data

PADDING_DAYS = 200  # calendar-day buffer so week one already has 12 weeks of trailing history


def week_mondays(start: str, end: str) -> list[pd.Timestamp]:
    """Every Monday in [start, end] — the candidate decision days."""
    return list(pd.date_range(start, end, freq="W-MON"))


def run(symbols: list[str], start: str, end: str, capital: float = 30000.0, top_k: int = 12,
        llm_weight: float = 0.0, feature_fn=None,
        hold_winners: bool = False) -> tuple[list[dict], list[dict], list[dict]]:
    """Simulate every week in [start, end]. Returns (trades, weekly_summary, weekly_ic).

    hold_winners=False: everything exits by Friday (today's live behaviour).
    hold_winners=True: a position re-picked on Monday is kept — no sell-and-rebuy
    round trip — and exits on a barrier hit or when it drops out of the basket.

    feature_fn overrides baseline.features — the noise gate swaps in random
    features here. weekly_ic is the rank correlation between score and realized
    return across the full scored universe, not just the picks (plan-backtest §5).
    """
    upper = config.strategy("upper_barrier")
    lower = config.strategy("lower_barrier")
    feature_fn = feature_fn or baseline.features

    fetch_start = (pd.Timestamp(start) - pd.Timedelta(days=PADDING_DAYS)).date().isoformat()
    fetch_end = (pd.Timestamp(end) + pd.Timedelta(days=1)).date().isoformat()
    history = bt_data.fetch_all(symbols, fetch_start, fetch_end)

    cash = capital
    held = {}  # ticker -> {entry, qty, since, score, buy_charge}
    trades, weekly, weekly_ic = [], [], []

    def close(ticker: str, pos: dict, price: float, week_id: str, outcome: str,
              exit_day=None) -> None:
        nonlocal cash
        sell_value = price * pos["qty"]
        charge = costs.side_cost(sell_value, "sell")
        cash += sell_value - charge
        trades.append({
            "week": week_id, "ticker": ticker, "score": pos["score"], "qty": pos["qty"],
            "entry": pos["entry"], "exit": price, "outcome": outcome, "exit_day": exit_day,
            "entered": pos["since"], "charge": pos["buy_charge"] + charge,
            "pnl": sell_value - pos["entry"] * pos["qty"] - pos["buy_charge"] - charge,
        })

    for monday in week_mondays(start, end):
        friday = monday + pd.Timedelta(days=4)
        week = bt_data.week_bars(history, monday, friday)
        if not week:
            continue  # holiday week, no trading

        prior = bt_data.as_of(history, monday)  # only data through the prior close
        feats = {s: f for s, df in prior.items() if (f := feature_fn(df))}
        if not feats:
            continue
        week_id = monday.date().isoformat()
        entry_prices = {s: float(df["open"].iloc[0]) for s, df in week.items()}

        ranked = baseline.rank(feats, llm_weight=llm_weight)  # full universe, for IC only
        realized = {s: float(df["close"].iloc[-1] / df["open"].iloc[0] - 1)
                    for s, df in week.items()}
        scored = {s: sc for s, sc in ranked if s in realized}
        weekly_ic.append({
            "week": week_id, "n": len(scored),
            "ic": metrics.ic(scored.values(), [realized[s] for s in scored])
            if len(scored) >= 5 else None,
        })

        # portfolio value at Monday open sizes this week's slots
        value = cash + sum(p["qty"] * entry_prices.get(t, p["entry"]) for t, p in held.items())
        basket = strategy.pick_basket(feats, entry_prices, value, top_k, llm_weight=llm_weight)
        picked = {p["ticker"] for p in basket}

        # Monday rotation: sell names that fell out of the basket, keep re-picked ones
        for ticker in list(held):
            if (ticker not in picked or not hold_winners) and ticker in entry_prices:
                close(ticker, held.pop(ticker), entry_prices[ticker], week_id, "rotated")

        for pick in basket:
            if pick["ticker"] in held:
                continue  # kept from last week — the whole point of hold_winners
            buy_value = pick["price"] * pick["qty"]
            charge = costs.side_cost(buy_value, "buy")
            if buy_value + charge > cash:
                continue  # capital still tied up in held positions
            cash -= buy_value + charge
            held[pick["ticker"]] = {"entry": pick["price"], "qty": pick["qty"],
                                    "since": week_id, "score": pick["score"],
                                    "buy_charge": charge}

        # walk the week's bars; barriers stay anchored to each position's original entry
        for ticker in list(held):
            bars = week.get(ticker)
            if bars is None:
                continue  # suspended this week; position carries
            pos = held[ticker]
            outcome, exit_price, exit_day = label(
                pos["entry"], bars["high"].tolist(), bars["low"].tolist(),
                bars["close"].tolist(), upper, lower,
            )
            if outcome != "neutral":
                close(ticker, held.pop(ticker), exit_price, week_id, outcome, exit_day)
            elif not hold_winners:  # Friday time barrier (live behaviour today)
                close(ticker, held.pop(ticker), exit_price, week_id, "neutral", exit_day)

        value_end = cash
        for t, p in held.items():
            last = float(week[t]["close"].iloc[-1]) if t in week else p["entry"]
            value_end += p["qty"] * last
        weekly.append({"week": week_id, "capital_start": value, "capital_end": value_end,
                       "return": value_end / value - 1})
    return trades, weekly, weekly_ic
