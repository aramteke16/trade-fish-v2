"""The weekly decision: rank the universe, size the top-k basket.

Pure function, no I/O — live weekly_score.py and the backtest engine both call
this with their own data, so they run the identical decision logic.
"""

from tradefish.model import baseline


def pick_basket(feats: dict[str, dict], entry_prices: dict[str, float], capital: float,
                top_k: int, llm: dict[str, float] | None = None,
                llm_weight: float = 0.0) -> list[dict]:
    """Rank the universe, return the top-k picks sized against capital.

    Each pick is {ticker, qty, price, score}. Walks down the ranking when a
    share price exceeds its slot budget, so unaffordable names don't leave
    slots empty.
    """
    ranked = baseline.rank(feats, llm, llm_weight)
    budget = capital * 0.99 / top_k  # 1% buffer for charges
    basket = []
    for symbol, score in ranked:
        if len(basket) >= top_k:
            break
        price = entry_prices.get(symbol)
        if not price:
            continue
        qty = int(budget / price)
        if qty < 1:  # one share already costs more than the slot
            continue
        basket.append({"ticker": symbol, "qty": qty, "price": price, "score": score})
    return basket
