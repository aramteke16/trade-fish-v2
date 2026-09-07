"""Algo v5 rules engine — pure functions over price history. See docs/algo-v5.md.

No I/O, no database: callers pass price frames in and get decisions out, so the
same code runs in the backtest and in production.
"""

import hashlib
import logging

import pandas as pd

logger = logging.getLogger(__name__)

MOM_SKIP = 22          # skip the most recent month (12-1 momentum)
MOM_LOOKBACK = 252     # ~12 months of sessions
TREND_WINDOW = 200     # stock's own trend filter
CORR_WINDOW = 126      # ~6 months for the correlation check
MIN_HISTORY = 260      # bars needed before a stock is scorable


def club_status(history: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Momentum and trend per symbol. Index: symbol. Columns: mom, trend, member."""
    rows = {}
    for sym, df in history.items():
        close = df["close"].dropna()
        if len(close) < MIN_HISTORY:
            continue
        mom = close.iloc[-MOM_SKIP] / close.iloc[-MOM_LOOKBACK] - 1.0
        trend = bool(close.iloc[-1] > close.iloc[-TREND_WINDOW:].mean())
        rows[sym] = {"mom": float(mom), "trend": trend, "member": bool(mom > 0 and trend)}
    return pd.DataFrame.from_dict(rows, orient="index")


def market_state(nifty: pd.DataFrame, vol_percentile: float = 0.90) -> dict:
    """Gate (NIFTY above its 50dma) and storm brake (21d vol above its own tail)."""
    close = nifty["close"].dropna()
    if len(close) < MIN_HISTORY:
        return {"gate_open": False, "storm": False, "reason": "insufficient nifty history"}
    dma50 = float(close.iloc[-50:].mean())
    vol21 = close.pct_change().rolling(21).std()
    threshold = float(vol21.expanding(min_periods=252).quantile(vol_percentile).iloc[-1])
    current = float(vol21.iloc[-1])
    gate_open = float(close.iloc[-1]) > dma50
    storm = current >= threshold
    return {"gate_open": gate_open, "storm": storm,
            "close": float(close.iloc[-1]), "dma50": dma50,
            "vol21": current, "vol_threshold": threshold,
            "reason": "open" if gate_open else "nifty below 50dma"}


def neutral_order(symbols) -> list[str]:
    """Deliberately opinion-free ordering — any return-correlated sort is a picker."""
    return sorted(symbols, key=lambda s: hashlib.sha1(s.encode()).hexdigest())


def _correlated(history: dict[str, pd.DataFrame], candidate: str, held: list[str],
                cap: float) -> bool:
    cand = history[candidate]["close"].pct_change().iloc[-CORR_WINDOW:]
    for sym in held:
        if sym not in history:
            continue
        other = history[sym]["close"].pct_change().iloc[-CORR_WINDOW:]
        pair = pd.concat([cand, other], axis=1).dropna()
        if len(pair) > 60 and pair.iloc[:, 0].corr(pair.iloc[:, 1]) > cap:
            return True
    return False


def select_buys(history: dict[str, pd.DataFrame], status: pd.DataFrame,
                held: list[str], n_slots: int, corr_cap: float = 0.6) -> list[str]:
    """Club members not already held, neutral order, correlation-filtered."""
    if n_slots <= 0 or status.empty:
        return []
    members = [s for s in status.index[status["member"]] if s not in held]
    picks = []
    for sym in neutral_order(members):
        if len(picks) >= n_slots:
            break
        if sym not in history:
            continue
        if _correlated(history, sym, held + picks, corr_cap):
            continue
        picks.append(sym)
    return picks


def select_sells(status: pd.DataFrame, held: list[str]) -> dict[str, str]:
    """Holdings that lost club membership, with the reason for the log."""
    out = {}
    for sym in held:
        if sym not in status.index:
            out[sym] = "no_data"
        elif status.loc[sym, "mom"] <= 0:
            # a stock failing both tests is reported as momentum death: the
            # year-long verdict is more informative than the trend break
            out[sym] = "momentum_death"
        elif not status.loc[sym, "trend"]:
            out[sym] = "trend_break"
    return out


def build_universe(history: dict[str, pd.DataFrame], min_sessions: int = 220,
                   min_close: float = 30.0, min_value: float = 1e7) -> list[str]:
    """Liquidity filter over the trailing year of the supplied history."""
    cutoff = None
    for df in history.values():
        if len(df):
            last = df.index[-1]
            cutoff = last if cutoff is None or last > cutoff else cutoff
    if cutoff is None:
        return []
    year_start = cutoff - pd.DateOffset(years=1)
    keep = []
    for sym, df in history.items():
        year = df[df.index >= year_start]
        if len(year) < min_sessions or year["close"].iloc[-1] < min_close:
            continue
        if (year["close"] * year["volume"]).median() < min_value:
            continue
        keep.append(sym)
    return sorted(keep)
