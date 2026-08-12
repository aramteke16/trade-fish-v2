"""Phase 1 scorer: cross-sectional momentum blend (plan §Phase 1 benchmark).

This is the plan's "equal-weight top-momentum basket" — the dumb benchmark the
LightGBM ranker must later beat to earn its place.
"""

import pandas as pd

MIN_DAYS = 65  # need 12w of history + a buffer


def features(df: pd.DataFrame) -> dict | None:
    c = df["close"]
    if len(c) < MIN_DAYS:
        return None
    return {
        "mom_1w": float(c.iloc[-1] / c.iloc[-6] - 1),
        "mom_4w": float(c.iloc[-1] / c.iloc[-21] - 1),
        "mom_12w": float(c.iloc[-1] / c.iloc[-61] - 1),
        "vol": float(c.pct_change().tail(60).std()) or 1e-9,
    }


def rank(feats: dict[str, dict], llm: dict[str, float] | None = None,
         llm_weight: float = 0.0) -> list[tuple[str, float]]:
    """Standardize cross-sectionally (plan §4), blend momentum + LLM. Best first."""
    if not feats:
        return []
    df = pd.DataFrame(feats).T
    z = (df - df.mean()) / (df.std() + 1e-12)
    score = z[["mom_1w", "mom_4w", "mom_12w"]].mean(axis=1) - 0.5 * z["vol"]
    if llm and llm_weight:
        # names with no news sit at 0 — absence of news is information, not a gap
        raw = pd.Series({t: llm.get(t, 0.0) for t in df.index})
        lz = (raw - raw.mean()) / raw.std() if raw.std() > 0 else raw * 0
        score = (1 - llm_weight) * score + llm_weight * lz
    return sorted(score.items(), key=lambda kv: kv[1], reverse=True)
