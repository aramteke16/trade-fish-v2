"""DASRL clone on NSE midcap pharma.

The ranker is the paper's long-intensity score: 90 sessions, top 3, names
refreshed when the next session is a new month. Weights are set on that same
refresh and then held. Drift inside the month is not traded. The PPO is the
paper's 256/128 network. Reward step sizes are not in the paper; the constants
below were frozen before the 2024 test. Train only on sessions before
2024-01-01. The 2024 onward path is scored once.

Costs, tax, and the last-session rule follow india-market-learnings.md.
Skip-month and a trend cash filter are not applied: the note lists them as
later changes and does not define the trend rule.
"""

from __future__ import annotations

import csv
import json
import math
import os
import time
import urllib.error
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
BARS_PATH = DATA / "pharma_bars.csv"
INDEX_PATH = DATA / "nifty_pharma_index.csv"
OUT_PATH = DATA / "pharma_dasrl_india_result.json"
NOTES_PATH = DATA / "pharma_fetch_notes.txt"
INDEX_KEY = "NSE_INDEX|Nifty Pharma"
INDEX_SYMBOL = "NIFTYPHARMA"
IST = ZoneInfo("Asia/Kolkata")

# Nifty Midcap 150 drug makers. Hospitals, diagnostics, and devices stay out.
PHARMA = (
    "ABBOTINDIA", "AJANTPHARM", "ALKEM", "ANTHEM", "AUROPHARMA", "BIOCON",
    "GLAXO", "GLENMARK", "IPCALAB", "LAURUSLABS", "LUPIN", "MANKIND",
)

# Research small-cap path. Left empty so an old run is not restarted.
# The live famous small caps are PHARMA_FAMOUS.
PHARMA_SMALL = ()

# Same drug makers. The weekly buy ranks this list, POWER, the famous small
# caps below, and current holdings.
# A holding stays eligible even when it is not a midcap. Names join when one year old.
PHARMA_ALL = PHARMA

# Nifty Midcap 150 names from generation, transmission, and power equipment.
# Large caps stay out. Oil, gas, lenders, and home-appliance brands stay out.
# Famous small caps in the same industries are POWER_FAMOUS.
POWER = (
    "APARINDS", "BHEL", "GVT&D", "JSWENERGY", "KEI", "NHPC", "NLCINDIA",
    "NTPCGREEN", "PREMIERENE", "SUZLON", "THERMAX", "TORNTPOWER", "WAAREEENER",
)

# Nifty Smallcap 250 drug makers and CDMOs. Hospitals, diagnostics, devices,
# and chemicals stay out. A name listed under one year stays out. A last
# close under ₹20 stays out. Names outside this index stay out.
PHARMA_FAMOUS = (
    "CAPLIPOINT", "COHANCE", "CONCORDBIO", "EMCURE", "GLAND", "GRANULES",
    "NATCOPHARM", "NEULANDLAB", "ONESOURCE", "PPLPHARMA", "RUBICON",
    "SAILIFE", "SYNGENE", "WOCKPHARMA",
)

# Nifty Smallcap 250 generation, transmission, and electrical equipment.
# Same age and price gates. JPPOWER and RPOWER are under ₹20 and stay out.
# CLEANMAX, EMMVEE, and VEDPOWER are under one year old and stay out.
POWER_FAMOUS = (
    "ACMESOLAR", "AZAD", "CESC", "ELECON", "FINCABLES", "INOXWIND", "KEC",
    "KPIL", "MTARTECH", "NAVA", "RRKABEL", "SCHNEIDER", "SJVN", "TARIL",
    "TDPOWERSYS", "TECHNOE", "TRITURBINE",
)

FETCH_START = date(2018, 1, 1)
TEST_START = date(2024, 1, 1)
CAPITAL = 1_000_000.0
LIM_WINDOW = 90
LIM_DELTA = 0.003
N_HOLD = 3
SEED = 7

# Paper Table 2. Epochs are collection rounds of up to 1000 train steps.
ACTOR_LR = 3e-4
GAMMA = 0.98
CLIP = 0.2
VF_COEF = 0.5
ENTROPY_COEF = 0.01
GAE_LAMBDA = 0.95
GRAD_CLIP = 0.5
ACTION_NOISE = 0.1
EPOCHS = 500
STEPS_PER_EPOCH = 1000
UPDATE_PASSES = 4

# Not printed in the paper. Do not change after looking at the 2024 result.
C_POS = 0.05
C_NEG = 0.05
C_STEP = 0.01
D_MIN = 2
HORIZ_CAP = 0.05
END_BONUS = 0.1


def load_token() -> str:
    # The file wins, so a config-page edit is used on the next price request.
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text().splitlines():
            if line.startswith("TRADEFISH_UPSTOX_ACCESS_TOKEN="):
                token = line.split("=", 1)[1].strip()
                if token:
                    return token
    token = os.environ.get("TRADEFISH_UPSTOX_ACCESS_TOKEN", "").strip()
    if token:
        return token
    raise RuntimeError("TRADEFISH_UPSTOX_ACCESS_TOKEN is missing from .env")


def upstox_get(token: str, path: str, query: dict | None = None) -> dict:
    url = "https://api.upstox.com" + path
    if query:
        url += "?" + urlencode(query)
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "tradefish-backtester/0.1",
        },
    )
    last_error = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=40) as response:
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code not in (429, 500, 502, 503):
                body = exc.read().decode("utf-8", "replace")[:300]
                raise RuntimeError(f"Upstox {exc.code} on {path}: {body}") from None
            time.sleep(1.5 * (attempt + 1))
        except urllib.error.URLError as exc:
            last_error = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Upstox failed on {path}: {last_error}")


def resolve_equity(token: str, symbol: str) -> str:
    payload = upstox_get(
        token,
        "/v2/instruments/search",
        {
            "query": symbol,
            "exchanges": "NSE",
            "segments": "EQ",
            "page_number": "1",
            "records": "30",
        },
    )
    keys = []
    for item in payload.get("data") or []:
        if (
            str(item.get("trading_symbol", "")).upper() == symbol
            and item.get("segment") == "NSE_EQ"
            and item.get("instrument_type") in ("EQ", "BE")
            and str(item.get("instrument_key", "")).startswith("NSE_EQ|")
        ):
            keys.append(item["instrument_key"])
    if len(keys) != 1:
        raise RuntimeError(f"{symbol}: expected one NSE EQ key, found {len(keys)}")
    return keys[0]


def parse_candles(payload: dict, symbol: str) -> list[tuple]:
    candles = (payload.get("data") or {}).get("candles")
    if not isinstance(candles, list):
        raise RuntimeError(f"{symbol}: malformed candle payload")
    rows = []
    for candle in candles:
        stamp = datetime.fromisoformat(str(candle[0])).astimezone(IST).date()
        open_, high, low, close = (float(candle[1]), float(candle[2]), float(candle[3]), float(candle[4]))
        volume = int(float(candle[5]))
        if min(open_, high, low, close) <= 0:
            continue
        rows.append((symbol, stamp.isoformat(), open_, high, low, close, volume))
    return rows


def download_daily(token: str, key: str, symbol: str, start: date, end: date) -> list[tuple]:
    encoded = quote(key, safe="")
    payload = upstox_get(
        token,
        f"/v3/historical-candle/{encoded}/days/1/{end.isoformat()}/{start.isoformat()}",
    )
    return parse_candles(payload, symbol)


def fetch_all(token: str) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    end = date.today()
    rows = []
    notes = []
    for symbol in UNIVERSE:
        try:
            key = resolve_equity(token, symbol)
            got = download_daily(token, key, symbol, FETCH_START, end)
        except RuntimeError as exc:
            notes.append(f"{symbol}: {exc}")
            continue
        if not got:
            notes.append(f"{symbol}: no bars")
            continue
        rows.extend(got)
        notes.append(f"{symbol}: {got[-1][1]} .. {got[0][1]} n={len(got)}")
        time.sleep(0.25)
    index_rows = []
    if INDEX_KEY:
        try:
            index_rows = download_daily(token, INDEX_KEY, INDEX_SYMBOL, FETCH_START, end)
        except RuntimeError as exc:
            notes.append(f"{INDEX_SYMBOL}: {exc}")
    with BARS_PATH.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["symbol", "date", "open", "high", "low", "close", "volume"])
        writer.writerows(rows)
    with INDEX_PATH.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["symbol", "date", "open", "high", "low", "close", "volume"])
        writer.writerows(index_rows)
    NOTES_PATH.write_text("\n".join(notes) + "\n")


def ensure_pharma_all_bars(token: str) -> None:
    """Fill data/pharma_all_bars.csv. Never rewrite data/pharma_bars.csv.

    Each new symbol is appended as it arrives, so a stopped fetch can resume.
    """
    dest = DATA / "pharma_all_bars.csv"
    notes_path = DATA / "pharma_all_fetch_notes.txt"
    end = date(2026, 10, 15)
    header = ["symbol", "date", "open", "high", "low", "close", "volume"]
    DATA.mkdir(parents=True, exist_ok=True)
    have = set()
    if dest.exists():
        with dest.open() as handle:
            for row in csv.DictReader(handle):
                have.add(row["symbol"])
    else:
        with dest.open("w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(header)
            source = DATA / "pharma_bars.csv"
            if source.exists():
                for row in csv.DictReader(source.open()):
                    if row["symbol"] not in PHARMA_ALL or row["date"] > end.isoformat():
                        continue
                    writer.writerow([row[col] for col in header])
                    have.add(row["symbol"])
    missing = [symbol for symbol in PHARMA_ALL if symbol not in have]
    notes = [f"already had {len(have)} names; fetching {len(missing)}"]
    print(notes[0], flush=True)
    for symbol in missing:
        try:
            key = resolve_equity(token, symbol)
            got = download_daily(token, key, symbol, FETCH_START, end)
        except RuntimeError as exc:
            notes.append(f"{symbol}: {exc}")
            print(notes[-1], flush=True)
            time.sleep(0.3)
            continue
        if not got:
            notes.append(f"{symbol}: no bars")
        else:
            with dest.open("a", newline="") as handle:
                writer = csv.writer(handle)
                for row in got:
                    if row[1] <= end.isoformat():
                        writer.writerow(row)
            have.add(symbol)
            notes.append(f"{symbol}: {got[-1][1]} .. {got[0][1]} n={len(got)}")
        print(notes[-1], flush=True)
        time.sleep(0.3)
    notes_path.write_text("\n".join(notes) + "\n")
    print(f"bars {dest.name} symbols {len(have)} missing {len(PHARMA_ALL) - len(have)}", flush=True)


def _last_dates(path: Path) -> dict[str, str]:
    last = {}
    if not path.exists():
        return last
    with path.open() as handle:
        for row in csv.DictReader(handle):
            symbol = row["symbol"]
            if row["date"] > last.get(symbol, ""):
                last[symbol] = row["date"]
    return last


def refresh_latest_bars(token: str) -> None:
    """Append sessions newer than the file. Does not rewrite older bars."""
    end = date.today()
    last_by = _last_dates(BARS_PATH)
    index_last = _last_dates(INDEX_PATH).get(INDEX_SYMBOL, "")
    if INDEX_KEY and index_last:
        try:
            got = download_daily(token, INDEX_KEY, INDEX_SYMBOL, date.fromisoformat(index_last), end)
        except RuntimeError as exc:
            print(f"{INDEX_SYMBOL}: {exc}", flush=True)
            got = []
        new_rows = [row for row in got if row[1] > index_last]
        if new_rows:
            with INDEX_PATH.open("a", newline="") as handle:
                csv.writer(handle).writerows(new_rows)
            index_last = max(row[1] for row in new_rows)
            print(f"{INDEX_SYMBOL}: +{len(new_rows)} through {index_last}", flush=True)
    added = 0
    for symbol in PHARMA_ALL:
        prev = last_by.get(symbol, "")
        if index_last and prev >= index_last:
            continue
        start = date.fromisoformat(prev) if prev else FETCH_START
        try:
            key = resolve_equity(token, symbol)
            got = download_daily(token, key, symbol, start, end)
        except RuntimeError as exc:
            print(f"{symbol}: {exc}", flush=True)
            time.sleep(0.25)
            continue
        new_rows = [row for row in got if row[1] > prev]
        if new_rows:
            with BARS_PATH.open("a", newline="") as handle:
                csv.writer(handle).writerows(new_rows)
            added += len(new_rows)
            print(f"{symbol}: +{len(new_rows)} through {new_rows[0][1]}", flush=True)
        time.sleep(0.25)
    print(f"refresh added {added}", flush=True)


@dataclass
class Series:
    dates: list[date]
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray


def load_csv(path: Path) -> dict[str, Series]:
    grouped = defaultdict(list)
    with path.open() as handle:
        for row in csv.DictReader(handle):
            grouped[row["symbol"]].append(row)
    out = {}
    for symbol, rows in grouped.items():
        rows.sort(key=lambda item: item["date"])
        out[symbol] = Series(
            dates=[date.fromisoformat(item["date"]) for item in rows],
            open=np.array([float(item["open"]) for item in rows]),
            high=np.array([float(item["high"]) for item in rows]),
            low=np.array([float(item["low"]) for item in rows]),
            close=np.array([float(item["close"]) for item in rows]),
        )
    return out


def calendar(books: dict[str, Series]) -> list[date]:
    days = set()
    for series in books.values():
        days.update(series.dates)
    return sorted(days)


def index_of(series: Series) -> dict[date, int]:
    return {day: i for i, day in enumerate(series.dates)}


def add_year(day: date) -> date:
    try:
        return day.replace(year=day.year + 1)
    except ValueError:
        return day.replace(year=day.year + 1, day=28)


# Zerodha NSE delivery schedule in india-market-learnings.md. One published
# rate for the whole window: exchange charges did move, and this file uses
# the figure that note tells the backtester to use.
EXCHANGE_RATE = 0.0000307  # 0.00307%
SEBI_RATE = 0.000001  # Rs 10 per crore
IPFT_RATE = 0.000001  # Rs 10 per crore
STT_RATE = 0.001  # 0.1% both sides
STAMP_RATE = 0.00015  # 0.015% on the buy only
DP_SELL = 15.34  # GST already inside, once per symbol per sell day
GST_RATE = 0.18


def delivery_fee(side: str, notional: float, charge_dp: bool) -> tuple[float, float]:
    """Cash fee, and the part that reduces the capital gain.

    GST is on the exchange charge and SEBI only. STT is paid in cash and is
    not deducted again inside the gain. Stamp, IPFT, GST, and DP are deductible.
    """
    stt = notional * STT_RATE
    stamp = notional * STAMP_RATE if side == "buy" else 0.0
    exchange_fee = notional * EXCHANGE_RATE
    sebi = notional * SEBI_RATE
    ipft = notional * IPFT_RATE
    dp = DP_SELL if charge_dp and side == "sell" else 0.0
    gst = GST_RATE * (exchange_fee + sebi)
    cash_fee = stt + stamp + exchange_fee + sebi + ipft + dp + gst
    return cash_fee, cash_fee - stt


def financial_year(day: date) -> int:
    return day.year if day.month >= 4 else day.year - 1


def apply_buy(lots, symbol: str, qty: int, price: float, day: date, deductible: float) -> None:
    lots.setdefault(symbol, []).append([qty, price, day, deductible])


def apply_sell(lots, tax_events, symbol: str, qty: int, price: float, day: date, deductible: float) -> None:
    """FIFO. deductible is the sell-side amount, excluding STT, for this sale."""
    book = lots.get(symbol, [])
    left = qty
    while left and book:
        lot_qty, lot_price, lot_day, lot_ded = book[0]
        take = min(left, lot_qty)
        buy_ded = lot_ded * take / lot_qty
        sell_ded = deductible * take / qty
        gain = take * (price - lot_price) - buy_ded - sell_ded
        tax_events.append((day, lot_day, gain))
        left -= take
        if take == lot_qty:
            book.pop(0)
        else:
            book[0] = [lot_qty - take, lot_price, lot_day, lot_ded - buy_ded]


def capital_gains_tax(events) -> float:
    """STCG 20% at 12 months or less, including a sale on the anniversary.

    LTCG 12.5% above Rs 1.25 lakh per financial year, after set-off, plus 4% cess.
    Short-term losses offset short-term gains, then long-term gains.
    Long-term losses offset long-term gains only.
    Unused losses carry forward for at most 8 following financial years.
    """
    if not events:
        return 0.0
    by_fy = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])
    years = set()
    for sell_day, buy_day, gain in events:
        fy = financial_year(sell_day)
        years.add(fy)
        long = sell_day > add_year(buy_day)
        slot = by_fy[fy]
        if gain >= 0:
            slot[2 if long else 0] += gain
        else:
            slot[3 if long else 1] += -gain
    stcl_carry = []
    ltcl_carry = []
    tax = 0.0
    for fy in range(min(years), max(years) + 1):
        stcg, stcl, ltcg, ltcl = by_fy[fy]
        use = min(stcl, stcg)
        stcg -= use
        stcl -= use
        use = min(stcl, ltcg)
        ltcg -= use
        stcl -= use
        use = min(ltcl, ltcg)
        ltcg -= use
        ltcl -= use
        still = []
        for origin, amount in stcl_carry:
            if fy > origin + 8 or amount <= 0:
                continue
            use = min(amount, stcg)
            amount -= use
            stcg -= use
            use = min(amount, ltcg)
            amount -= use
            ltcg -= use
            if amount > 1e-6:
                still.append([origin, amount])
        stcl_carry = still
        still = []
        for origin, amount in ltcl_carry:
            if fy > origin + 8 or amount <= 0:
                continue
            use = min(amount, ltcg)
            amount -= use
            ltcg -= use
            if amount > 1e-6:
                still.append([origin, amount])
        ltcl_carry = still
        if ltcg > 0:
            ltcg = max(0.0, ltcg - 125_000.0)
        tax += stcg * 0.20 * 1.04
        tax += ltcg * 0.125 * 1.04
        if stcl > 1e-6:
            stcl_carry.append([fy, stcl])
        if ltcl > 1e-6:
            ltcl_carry.append([fy, ltcl])
    return max(0.0, tax)


class Book:
    def __init__(self, symbols: dict[str, Series]):
        self.symbols = symbols
        self.loc = {symbol: index_of(series) for symbol, series in symbols.items()}
        self.dates = calendar(symbols)
        self.pos = {day: i for i, day in enumerate(self.dates)}

    def bar(self, symbol: str, day: date):
        slot = self.loc[symbol].get(day)
        if slot is None:
            return None
        series = self.symbols[symbol]
        return series.open[slot], series.high[slot], series.low[slot], series.close[slot]

    def close_on_or_before(self, symbol: str, day: date) -> float | None:
        series = self.symbols[symbol]
        # Dates are sorted. Walk back a short gap only.
        for _ in range(6):
            slot = self.loc[symbol].get(day)
            if slot is not None:
                return float(series.close[slot])
            day = day - timedelta(days=1)
        return None


def rsi(closes: np.ndarray, n: int = 14) -> float:
    if len(closes) < n + 1:
        return 50.0
    diff = np.diff(closes[-(n + 1):])
    gain = float(np.mean(np.clip(diff, 0, None)))
    loss = float(np.mean(np.clip(-diff, 0, None)))
    if loss == 0:
        return 100.0
    return 100.0 - 100.0 / (1.0 + gain / loss)


def ema_last(values: np.ndarray, n: int) -> float:
    alpha = 2.0 / (n + 1.0)
    out = float(values[0])
    for value in values[1:]:
        out = alpha * float(value) + (1.0 - alpha) * out
    return out


def atr(highs, lows, closes, n: int = 14) -> float:
    if len(closes) < n + 1:
        return 0.0
    prev = closes[-(n + 1):-1]
    tr = np.maximum(highs[-n:] - lows[-n:], np.maximum(np.abs(highs[-n:] - prev), np.abs(lows[-n:] - prev)))
    return float(np.mean(tr))


def lim_score(opens: np.ndarray, closes: np.ndarray, window: int | None = None) -> float:
    span = LIM_WINDOW if window is None else window
    if len(closes) < span:
        return 0.0
    window_o = opens[-span:]
    window_c = closes[-span:]
    factor = window_c / window_o * (1.0 - LIM_DELTA) ** 2
    good = factor[factor >= 1.0]
    if len(good) == 0:
        return 1.0
    return float(np.exp(np.sum(np.log(good))))


def history_until(series: Series, loc: dict[date, int], day: date, length: int):
    slot = loc.get(day)
    if slot is None or slot + 1 < length:
        return None
    start = slot + 1 - length
    return (
        series.open[start:slot + 1],
        series.high[start:slot + 1],
        series.low[start:slot + 1],
        series.close[start:slot + 1],
    )


def seasoned(series: Series, day: date) -> bool:
    """A name may be ranked once it is a year old.

    Bars were requested from 2018-01-01, so a history that starts on that day
    belongs to a company that was already listed. A later first bar is a listing.
    """
    first = series.dates[0]
    if first <= date(2018, 1, 5):
        return True
    return day >= add_year(first)


def ranked_on(book: Book, day: date, require_one_year: bool = False) -> list[tuple[str, float]]:
    raw = []
    for symbol, series in book.symbols.items():
        if require_one_year and not seasoned(series, day):
            continue
        hist = history_until(series, book.loc[symbol], day, LIM_WINDOW)
        if hist is None:
            continue
        raw.append((symbol, lim_score(hist[0], hist[3])))
    if not raw:
        return []
    best = max(score for _, score in raw)
    scale = max(1.0, best)
    scored = [(symbol, score / scale) for symbol, score in raw]
    scored.sort(key=lambda item: (-item[1], item[0]))
    return scored


def stock_features(hist) -> np.ndarray:
    opens, highs, lows, closes = hist
    ret = closes[-1] / closes[-2] - 1.0
    rets = closes[1:] / closes[:-1] - 1.0
    vol = float(np.std(rets[-20:], ddof=1)) if len(rets) >= 20 else 0.0
    macd = (ema_last(closes, 12) - ema_last(closes, 26)) / closes[-1]
    mid = float(np.mean(closes[-20:]))
    width = 0.0
    if len(closes) >= 20 and mid > 0:
        sd = float(np.std(closes[-20:], ddof=1))
        width = (4.0 * sd) / mid
    momentum = closes[-1] / closes[-21] - 1.0 if len(closes) >= 21 else 0.0
    return np.array(
        [
            ret,
            vol,
            rsi(closes) / 100.0,
            macd,
            width,
            atr(highs, lows, closes) / closes[-1],
            momentum,
        ],
        dtype=np.float64,
    )


def market_features(index: Series, loc: dict[date, int], day: date) -> np.ndarray:
    hist = history_until(index, loc, day, 21)
    if hist is None:
        return np.zeros(3)
    closes = hist[3]
    ret = closes[-1] / closes[-2] - 1.0
    rets = closes[1:] / closes[:-1] - 1.0
    vol = float(np.std(rets[-20:], ddof=1)) if len(rets) >= 20 else 0.0
    mom = closes[-1] / closes[-21] - 1.0 if len(closes) >= 21 else 0.0
    return np.array([ret, vol, mom], dtype=np.float64)


def state_vector(book, index, index_loc, day, held, equity, peak, last_equity) -> np.ndarray:
    parts = [market_features(index, index_loc, day)]
    for symbol in held:
        hist = history_until(book.symbols[symbol], book.loc[symbol], day, 30)
        parts.append(stock_features(hist)[:6] if hist is not None else np.zeros(6))
    while len(parts) < 1 + N_HOLD:
        parts.append(np.zeros(6))
    drawdown = 0.0 if peak <= 0 else equity / peak - 1.0
    day_ret = 0.0 if last_equity <= 0 else equity / last_equity - 1.0
    parts.append(np.array([equity / CAPITAL, drawdown, day_ret], dtype=np.float64))
    return np.concatenate(parts)


class AdamMLP:
    def __init__(self, sizes, lr, seed, last_softplus=False):
        rng = np.random.default_rng(seed)
        self.lr = lr
        self.last_softplus = last_softplus
        self.W, self.b = [], []
        self.mW, self.vW, self.mb, self.vb = [], [], [], []
        for fan_in, fan_out in zip(sizes[:-1], sizes[1:]):
            scale = np.sqrt(2.0 / fan_in)
            self.W.append(rng.normal(0, scale, size=(fan_in, fan_out)))
            self.b.append(np.zeros(fan_out))
            self.mW.append(np.zeros_like(self.W[-1]))
            self.vW.append(np.zeros_like(self.W[-1]))
            self.mb.append(np.zeros_like(self.b[-1]))
            self.vb.append(np.zeros_like(self.b[-1]))
        self.step = 0

    def forward(self, x, cache=False):
        acts = [x]
        current = x
        for layer, (weight, bias) in enumerate(zip(self.W, self.b)):
            current = current @ weight + bias
            last = layer == len(self.W) - 1
            if not last:
                current = np.maximum(current, 0.0)
            elif self.last_softplus:
                current = np.log1p(np.exp(np.clip(current, -20, 20)))
            if cache:
                acts.append(current)
        return (current, acts) if cache else current

    def apply_grad(self, grads_w, grads_b):
        self.step += 1
        scale = 1.0
        norm = math.sqrt(
            sum(float(np.sum(item ** 2)) for item in grads_w)
            + sum(float(np.sum(item ** 2)) for item in grads_b)
        )
        if norm > GRAD_CLIP:
            scale = GRAD_CLIP / (norm + 1e-8)
        beta1, beta2, eps = 0.9, 0.999, 1e-8
        for i in range(len(self.W)):
            gw = grads_w[i] * scale
            gb = grads_b[i] * scale
            self.mW[i] = beta1 * self.mW[i] + (1 - beta1) * gw
            self.vW[i] = beta2 * self.vW[i] + (1 - beta2) * (gw ** 2)
            self.mb[i] = beta1 * self.mb[i] + (1 - beta1) * gb
            self.vb[i] = beta2 * self.vb[i] + (1 - beta2) * (gb ** 2)
            mw = self.mW[i] / (1 - beta1 ** self.step)
            vw = self.vW[i] / (1 - beta2 ** self.step)
            mb = self.mb[i] / (1 - beta1 ** self.step)
            vb = self.vb[i] / (1 - beta2 ** self.step)
            self.W[i] -= self.lr * mw / (np.sqrt(vw) + eps)
            self.b[i] -= self.lr * mb / (np.sqrt(vb) + eps)


def gaussian_logprob(raw, mean, std):
    var = std ** 2
    return -0.5 * np.sum((raw - mean) ** 2 / var + math.log(2 * math.pi * var), axis=-1)


def weights_from_raw(raw):
    raw = np.maximum(raw, 1e-8)
    return raw / raw.sum(axis=-1, keepdims=True)


def actor_weights(actor: AdamMLP, state: np.ndarray, rng: np.random.Generator | None):
    mean = actor.forward(state[None, :])[0]
    if rng is None:
        raw = mean
        logp = None
    else:
        raw = mean + rng.normal(0, ACTION_NOISE, size=mean.shape)
        logp = float(gaussian_logprob(raw, mean, ACTION_NOISE))
    weights = np.atleast_1d(np.squeeze(weights_from_raw(np.atleast_2d(raw))))
    return weights, np.squeeze(raw), np.squeeze(mean), logp


def reward_for(day_return, total_return, up_days, terminal, equity) -> tuple[float, int]:
    base = float(np.clip(day_return, -0.5, 0.5))
    if total_return > 0:
        vertical = math.floor(total_return / 0.1) * C_POS
    else:
        vertical = -math.floor(abs(total_return) / 0.05) * C_NEG
    up_days = up_days + 1 if day_return > 0 else 0
    horizontal = min(up_days * C_STEP, HORIZ_CAP) if up_days >= D_MIN else 0.0
    bonus = END_BONUS if terminal and equity > CAPITAL else 0.0
    return base + vertical + horizontal + bonus, up_days


def month_changes(dates: list[date]) -> set[int]:
    marks = set()
    for i in range(len(dates) - 1):
        nxt = dates[i + 1]
        if nxt.month != dates[i].month or nxt.year != dates[i].year:
            marks.add(i)
    return marks


def week_changes(dates: list[date]) -> set[int]:
    """Decision days whose next session is the first session of a new week."""
    marks = set()
    for i in range(len(dates) - 1):
        cur = dates[i].isocalendar()
        nxt = dates[i + 1].isocalendar()
        if (nxt[0], nxt[1]) != (cur[0], cur[1]):
            marks.add(i)
    return marks


def trade_to(day, cash, shares, targets, opens, costs, lots, tax_events, dp_paid, allow_buys=True):
    """Sells first. A symbol is never bought and sold on the same day."""
    for symbol, qty in list(shares.items()):
        goal = targets.get(symbol, 0)
        price = opens.get(symbol)
        if qty <= goal or price is None or price <= 0:
            continue
        protected = sum(lot[0] for lot in lots.get(symbol, []) if lot[2] == day)
        sell_qty = min(qty - goal, qty - protected)
        if sell_qty <= 0:
            continue
        notional = sell_qty * price
        key = (day, symbol)
        charge_dp = key not in dp_paid
        dp_paid.add(key)
        cash_fee, deductible = delivery_fee("sell", notional, charge_dp)
        cash += notional - cash_fee
        shares[symbol] = qty - sell_qty
        costs[0] += cash_fee
        apply_sell(lots, tax_events, symbol, sell_qty, price, day, deductible)
    if not allow_buys:
        return cash, shares
    for symbol, goal in targets.items():
        held = shares.get(symbol, 0)
        price = opens.get(symbol)
        if goal <= held or price is None or price <= 0 or (day, symbol) in dp_paid:
            continue
        buy_qty = goal - held
        notional = buy_qty * price
        cash_fee, deductible = delivery_fee("buy", notional, False)
        if cash < notional + cash_fee:
            continue
        cash -= notional + cash_fee
        shares[symbol] = held + buy_qty
        costs[0] += cash_fee
        apply_buy(lots, symbol, buy_qty, price, day, deductible)
    return cash, shares


def liquidate_book(day, cash, shares, prices, costs, lots, tax_events, dp_paid):
    """Sell shares bought on an earlier day. Same-day buys stay unsold."""
    for symbol, qty in list(shares.items()):
        price = prices.get(symbol)
        if qty <= 0 or price is None or price <= 0:
            continue
        protected = sum(lot[0] for lot in lots.get(symbol, []) if lot[2] == day)
        sell_qty = qty - protected
        if sell_qty <= 0:
            continue
        notional = sell_qty * price
        key = (day, symbol)
        charge_dp = key not in dp_paid
        dp_paid.add(key)
        cash_fee, deductible = delivery_fee("sell", notional, charge_dp)
        cash += notional - cash_fee
        costs[0] += cash_fee
        apply_sell(lots, tax_events, symbol, sell_qty, price, day, deductible)
        shares[symbol] = qty - sell_qty
    equity = cash
    for symbol, qty in shares.items():
        price = prices.get(symbol)
        if qty > 0 and price:
            equity += qty * price
    return cash, equity


def equity_at(cash, shares, prices) -> float:
    total = cash
    for symbol, qty in shares.items():
        if qty and symbol in prices:
            total += qty * prices[symbol]
    return total


def target_shares(weights, names, equity, opens) -> dict[str, int]:
    targets = {}
    for weight, symbol in zip(weights, names):
        price = opens.get(symbol)
        if price is None or price <= 0 or weight <= 0:
            continue
        targets[symbol] = int(math.floor(equity * float(weight) / price))
    return targets


def simulate(book: Book, index: Series, policy, start_i: int, end_i: int, learn: bool, rankings: dict, ignore_test_cut: bool = False, rebalance_every: str = "month"):
    """policy(state, rng or None) -> weights. learn=True collects one reward path."""
    dates = book.dates
    index_loc = index_of(index)
    if rebalance_every == "week":
        rebalance = week_changes(dates)
    else:
        rebalance = month_changes(dates)
    cash = CAPITAL
    shares = {}
    names = []
    weights = np.array([])
    peak = CAPITAL
    last_equity = CAPITAL
    up_days = 0
    costs = [0.0]
    rows = []
    daily = []
    lots = {}
    tax_events = []
    dp_paid = set()
    held_weights = None
    held_state = None
    acc_reward = 0.0
    rng = np.random.default_rng(SEED) if learn else None
    for i in range(start_i, end_i):
        day = dates[i]
        if i + 1 >= len(dates):
            break
        fill_day = dates[i + 1]
        if learn and fill_day >= TEST_START:
            break
        if (not learn) and (not ignore_test_cut) and fill_day < TEST_START:
            continue
        if not learn and i < start_i:
            continue
        ranking = rankings[day]
        refresh = i in rebalance or held_weights is None
        if refresh:
            names = [symbol for symbol, _ in ranking[:N_HOLD]]
        if len(names) < N_HOLD:
            continue
        closes = {}
        for symbol in book.symbols:
            price = book.close_on_or_before(symbol, day)
            if price is not None:
                closes[symbol] = price
        equity = equity_at(cash, shares, closes) if shares else cash
        peak = max(peak, equity)
        if refresh:
            if learn and held_state is not None:
                rows.append((held_state, held_weights, acc_reward))
            acc_reward = 0.0
            state = state_vector(book, index, index_loc, day, names, equity, peak, last_equity)
            weights = policy(state, rng)
            held_state = state
            held_weights = weights
            opens = {}
            for symbol in names:
                bar = book.bar(symbol, fill_day)
                if bar is not None:
                    opens[symbol] = bar[0]
            usable = [symbol for symbol in names if symbol in opens]
            if len(usable) < N_HOLD:
                use_w = np.array([weights[names.index(symbol)] for symbol in usable])
                if use_w.sum() <= 0:
                    use_w = np.array([])
                    use_names = []
                else:
                    use_w = use_w / use_w.sum()
                    use_names = usable
            else:
                use_w = weights
                use_names = names
            if len(use_names):
                mark_equity = equity_at(cash, shares, opens) if shares else cash
                targets = target_shares(use_w, use_names, mark_equity, opens)
                last_fill = (not learn) and fill_day == dates[end_i - 1]
                cash, shares = trade_to(
                    fill_day, cash, shares, targets, opens, costs,
                    lots, tax_events, dp_paid, allow_buys=not last_fill,
                )
        fill_closes = {}
        for symbol, qty in shares.items():
            if qty <= 0:
                continue
            bar = book.bar(symbol, fill_day)
            if bar is not None:
                fill_closes[symbol] = bar[3]
        equity = equity_at(cash, shares, fill_closes)
        peak = max(peak, equity)
        day_return = equity / last_equity - 1.0
        total_return = equity / CAPITAL - 1.0
        terminal = (not learn and fill_day == dates[end_i - 1]) or (learn and i + 2 >= end_i)
        reward, up_days = reward_for(day_return, total_return, up_days, terminal, equity)
        acc_reward += reward
        daily.append((fill_day, equity, day_return))
        last_equity = equity
    if learn and held_state is not None:
        rows.append((held_state, held_weights, acc_reward))
    # Sell the test book at the last close. Buys were not filled on this session.
    if not learn and daily:
        last_day = daily[-1][0]
        last_closes = {}
        for symbol, qty in list(shares.items()):
            bar = book.bar(symbol, last_day)
            if qty > 0 and bar is not None:
                last_closes[symbol] = bar[3]
        cash, equity = liquidate_book(
            last_day, cash, shares, last_closes, costs, lots, tax_events, dp_paid,
        )
        daily[-1] = (last_day, equity, equity / daily[-2][1] - 1.0 if len(daily) > 1 else equity / CAPITAL - 1.0)
    tax = 0.0 if learn else max(0.0, capital_gains_tax(tax_events))
    return {
        "equity": daily[-1][1] if daily else CAPITAL,
        "costs": costs[0],
        "tax": tax,
        "daily": daily,
        "rows": rows,
    }


def metrics(daily) -> dict:
    if len(daily) < 3:
        return {}
    equity = np.array([row[1] for row in daily])
    rets = np.array([row[2] for row in daily])
    total = equity[-1] / CAPITAL - 1.0
    annual = (1.0 + total) ** (252.0 / len(rets)) - 1.0
    sharpe = 0.0 if rets.std(ddof=1) == 0 else float(rets.mean() / rets.std(ddof=1) * math.sqrt(252))
    downside = rets[rets < 0]
    sortino = 0.0 if len(downside) < 2 or downside.std(ddof=1) == 0 else float(
        rets.mean() / downside.std(ddof=1) * math.sqrt(252)
    )
    peak = np.maximum.accumulate(equity)
    drawdown = float(np.min(equity / peak - 1.0))
    return {
        "total_return": total,
        "annualized": annual,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": drawdown,
        "sessions": len(rets),
        "end_equity": float(equity[-1]),
    }


def buy_and_hold(book: Book, names: list[str], start: date) -> dict:
    dates = [day for day in book.dates if day >= start]
    if len(dates) < 3:
        return {}
    first = dates[0]
    opens = {}
    for symbol in names:
        bar = book.bar(symbol, first)
        if bar is not None:
            opens[symbol] = bar[0]
    names = list(opens)
    if not names:
        return {}
    weight = 1.0 / len(names)
    cash = CAPITAL
    shares = {}
    costs = [0.0]
    lots = {}
    tax_events = []
    dp_paid = set()
    targets = target_shares(np.full(len(names), weight), names, CAPITAL, opens)
    cash, shares = trade_to(
        first, cash, shares, targets, opens, costs, lots, tax_events, dp_paid, True,
    )
    daily = []
    last = CAPITAL
    for day in dates:
        closes = {}
        for symbol, qty in shares.items():
            bar = book.bar(symbol, day)
            if bar is not None:
                closes[symbol] = bar[3]
        equity = equity_at(cash, shares, closes)
        daily.append((day, equity, equity / last - 1.0))
        last = equity
    last_day = dates[-1]
    last_closes = {}
    for symbol, qty in shares.items():
        bar = book.bar(symbol, last_day)
        if qty > 0 and bar is not None:
            last_closes[symbol] = bar[3]
    cash, equity = liquidate_book(
        last_day, cash, shares, last_closes, costs, lots, tax_events, dp_paid,
    )
    daily[-1] = (last_day, equity, equity / daily[-2][1] - 1.0)
    out = metrics(daily)
    out["costs"] = costs[0]
    out["tax"] = capital_gains_tax(tax_events)
    out["net_profit"] = equity - CAPITAL - out["tax"]
    out["daily"] = daily
    return out


def collect_episode(book, index, actor, critic, start, end, rankings, rebalance_every="month"):
    def policy(state, rng):
        weights, raw, mean, logp = actor_weights(actor, state, rng)
        value = float(critic.forward(state[None, :])[0, 0])
        policy.cache.append((state, raw, mean, logp, value))
        return weights

    policy.cache = []
    result = simulate(book, index, policy, start, end, learn=True, rankings=rankings, rebalance_every=rebalance_every)
    rewards = [row[2] for row in result["rows"]]
    if not policy.cache:
        return None
    # simulate() appends rows even when policy stored the pre-noise sample.
    states = np.array([item[0] for item in policy.cache])
    raws = np.array([item[1] for item in policy.cache])
    means = np.array([item[2] for item in policy.cache])
    logps = np.array([item[3] for item in policy.cache])
    values = np.array([item[4] for item in policy.cache])
    rewards = np.array(rewards[: len(values)])
    adv = np.zeros_like(rewards)
    last = 0.0
    for t in range(len(rewards) - 1, -1, -1):
        nxt = values[t + 1] if t + 1 < len(values) else 0.0
        delta = rewards[t] + GAMMA * nxt - values[t]
        last = delta + GAMMA * GAE_LAMBDA * last
        adv[t] = last
    returns = adv + values
    return states, raws, means, logps, values, adv, returns, result["equity"]


def ppo_update(actor, critic, batch):
    states, raws, old_logps, adv, returns = batch
    adv = (adv - adv.mean()) / (adv.std() + 1e-8)
    n = len(states)
    order = np.arange(n)
    for _ in range(UPDATE_PASSES):
        np.random.default_rng(SEED + actor.step).shuffle(order)
        for start in range(0, n, 256):
            idx = order[start:start + 256]
            x = states[idx]
            mean, acts = actor.forward(x, cache=True)
            new_logp = gaussian_logprob(raws[idx], mean, ACTION_NOISE)
            ratio = np.exp(np.clip(new_logp - old_logps[idx], -20, 20))
            a = adv[idx]
            unclipped = ratio * a
            clipped = np.clip(ratio, 1 - CLIP, 1 + CLIP) * a
            policy_loss_elem = -np.minimum(unclipped, clipped)
            entropy = 0.5 * mean.shape[1] * (1 + math.log(2 * math.pi * ACTION_NOISE ** 2))
            # Actor backward from d(loss)/d(mean). Gaussian logp grad wrt mean is (raw-mean)/var.
            # The PPO ratio path is approximated by the clipped surrogate gradient through logp.
            grad_logp = (raws[idx] - mean) / (ACTION_NOISE ** 2)
            take_unclipped = (unclipped <= clipped).astype(np.float64)
            coef = np.where(take_unclipped, ratio, np.where((ratio < 1 - CLIP) | (ratio > 1 + CLIP), 0.0, ratio))
            # d(-min(rA, clip))/d(logp) ≈ -coef * adv, then chain to mean.
            d_mean = (-coef * a)[:, None] * grad_logp
            backprop(actor, acts, d_mean)
            value, v_acts = critic.forward(x, cache=True)
            d_value = VF_COEF * 2 * (value[:, 0] - returns[idx])
            backprop(critic, v_acts, d_value[:, None])
            _ = policy_loss_elem.mean() - ENTROPY_COEF * entropy


def backprop(net: AdamMLP, acts, d_out):
    grads_w = [None] * len(net.W)
    grads_b = [None] * len(net.b)
    grad = d_out
    for layer in range(len(net.W) - 1, -1, -1):
        incoming = acts[layer]
        if layer == len(net.W) - 1 and net.last_softplus:
            # acts[-1] is softplus(z). d(softplus)/dz = sigmoid(z).
            # Recover z is unnecessary: sigmoid(z) = 1 - exp(-softplus(z)).
            sigmoid = 1.0 - np.exp(-acts[layer + 1])
            grad = grad * sigmoid
        grads_w[layer] = incoming.T @ grad / len(incoming)
        grads_b[layer] = grad.mean(axis=0)
        grad = grad @ net.W[layer].T
        if layer > 0:
            grad = grad * (acts[layer] > 0)
    net.apply_grad(grads_w, grads_b)


def equal_weight_policy(state, rng):
    return np.full(N_HOLD, 1.0 / N_HOLD)


def make_ppo_policy(actor):
    def policy(state, rng):
        weights, _, _, _ = actor_weights(actor, state, None)
        return weights
    return policy


ACTOR_PATH = DATA / "pharma_all_actor.npz"
HOLDINGS_PATH = DATA / "pharma_holdings.json"
SIGNAL_PATH = DATA / "pharma_signal_latest.json"


def save_actor(actor: AdamMLP, path: Path) -> None:
    payload = {f"W{i}": weight for i, weight in enumerate(actor.W)}
    payload.update({f"b{i}": bias for i, bias in enumerate(actor.b)})
    np.savez(path, **payload)


def load_actor(path: Path) -> AdamMLP:
    blob = np.load(path)
    state_dim = 3 + 6 * N_HOLD + 3
    actor = AdamMLP([state_dim, 256, 128, N_HOLD], ACTOR_LR, SEED, last_softplus=True)
    for i in range(len(actor.W)):
        actor.W[i] = blob[f"W{i}"]
        actor.b[i] = blob[f"b{i}"]
    return actor


def read_account(marks: dict[str, float]) -> tuple[float, dict[str, int], float, float]:
    """Cash and shares the user still has to type in. Missing file means ₹10 lakh cash."""
    if not HOLDINGS_PATH.exists():
        return CAPITAL, {}, CAPITAL, CAPITAL
    payload = json.loads(HOLDINGS_PATH.read_text())
    cash = float(payload.get("cash", 0.0))
    shares = {symbol: int(qty) for symbol, qty in payload.get("shares", {}).items() if int(qty) > 0}
    equity = cash
    for symbol, qty in shares.items():
        price = marks.get(symbol)
        if price:
            equity += qty * price
    peak = float(payload["peak"]) if payload.get("peak") else equity
    last_equity = float(payload["last_equity"]) if payload.get("last_equity") else equity
    return cash, shares, max(peak, equity), last_equity


def run_signal(book: Book, index: Series, train_end: int) -> None:
    """Print the next delivery orders. This does not send an order."""
    if ACTOR_PATH.exists():
        actor = load_actor(ACTOR_PATH)
        print(f"loaded {ACTOR_PATH.name}", flush=True)
    else:
        rankings = {day: ranked_on(book, day, require_one_year=True) for day in book.dates}
        actor = train(book, index, train_end, rankings, rebalance_every="week")
        save_actor(actor, ACTOR_PATH)
        print(f"saved {ACTOR_PATH.name} from the pre-2024 weeks, seed {SEED}", flush=True)
    day = book.dates[-1]
    ranking = ranked_on(book, day, require_one_year=True)
    names = [symbol for symbol, _ in ranking[:N_HOLD]]
    if len(names) < N_HOLD:
        raise RuntimeError(f"{day}: only {len(names)} ranked names")
    marks = {}
    for symbol in book.symbols:
        price = book.close_on_or_before(symbol, day)
        if price is not None:
            marks[symbol] = price
    cash, held, peak, last_equity = read_account(marks)
    equity = cash
    for symbol, qty in held.items():
        if symbol in marks:
            equity += qty * marks[symbol]
    index_loc = index_of(index)
    state = state_vector(book, index, index_loc, day, names, equity, peak, last_equity)
    weights = make_ppo_policy(actor)(state, None)
    targets = target_shares(weights, names, equity, marks)
    orders = []
    for symbol in sorted(set(held) | set(targets)):
        goal = targets.get(symbol, 0)
        have = held.get(symbol, 0)
        delta = goal - have
        if delta == 0:
            continue
        price = marks.get(symbol)
        orders.append({
            "side": "BUY" if delta > 0 else "SELL",
            "symbol": symbol,
            "shares": abs(delta),
            "last_close": price,
            "rupees_at_last_close": None if price is None else round(abs(delta) * price, 2),
        })
    orders.sort(key=lambda item: (item["side"] != "SELL", item["symbol"]))
    book_rows = []
    for symbol, weight in zip(names, weights):
        book_rows.append({
            "symbol": symbol,
            "weight": float(weight),
            "target_shares": targets.get(symbol, 0),
            "last_close": marks.get(symbol),
        })
    payload = {
        "decision_close": day.isoformat(),
        "place_at": "next NSE open",
        "orders_sent": False,
        "equity_used": equity,
        "book": book_rows,
        "orders": orders,
    }
    SIGNAL_PATH.write_text(json.dumps(payload, indent=2))
    print(f"AS OF {day.isoformat()} close. Place at the next NSE open. No order was sent.", flush=True)
    print(f"Book value used for size: ₹{equity:.0f}", flush=True)
    for row in book_rows:
        print(
            f"HOLD {row['symbol']} {row['weight'] * 100:.1f}%  "
            f"{row['target_shares']} shares  close ₹{row['last_close']:.2f}",
            flush=True,
        )
    if not orders:
        print("No buy or sell. The account already matches the book.", flush=True)
    for order in orders:
        rupees = order["rupees_at_last_close"]
        amount = "price missing" if rupees is None else f"about ₹{rupees:.0f} at the last close"
        print(f"{order['side']} {order['symbol']} {order['shares']} shares, {amount}", flush=True)
    print("Sell before buy. Do not sell a share bought the same day.", flush=True)
    print(f"Wrote {SIGNAL_PATH.name}", flush=True)


def train(book, index, train_end_index, rankings, rebalance_every="month"):
    state_dim = 3 + 6 * N_HOLD + 3
    actor = AdamMLP([state_dim, 256, 128, N_HOLD], ACTOR_LR, SEED, last_softplus=True)
    critic = AdamMLP([state_dim, 256, 128, 1], ACTOR_LR, SEED + 1, last_softplus=False)
    start = 0
    for i, day in enumerate(book.dates):
        if len(rankings[day]) >= N_HOLD:
            start = i
            break
    cursor = start
    last_equity = CAPITAL
    for epoch in range(EPOCHS):
        stop = min(cursor + STEPS_PER_EPOCH, train_end_index)
        if stop - cursor < 30:
            cursor = start
            stop = min(cursor + STEPS_PER_EPOCH, train_end_index)
        episode = collect_episode(book, index, actor, critic, cursor, stop, rankings, rebalance_every)
        cursor = stop
        if episode is None:
            continue
        states, raws, means, logps, values, adv, returns, last_equity = episode
        ppo_update(actor, critic, (states, raws, logps, adv, returns))
        if epoch % 50 == 0 or epoch == EPOCHS - 1:
            print(f"epoch {epoch} train_equity {last_equity:.0f}", flush=True)
    return actor


LOOK_NOTE = (
    "Second look at the 2024-2026 pharma window. Ranker, reward constants, "
    "seed, and the pre-2024 train cut are unchanged. The first look remains "
    "data/pharma_dasrl_result.json."
)


def configure(sector: str) -> None:
    global BARS_PATH, INDEX_PATH, OUT_PATH, NOTES_PATH, INDEX_KEY, INDEX_SYMBOL, UNIVERSE, LOOK_NOTE
    if sector == "pharma":
        UNIVERSE = PHARMA
        BARS_PATH = DATA / "pharma_bars.csv"
        INDEX_PATH = DATA / "nifty_pharma_index.csv"
        OUT_PATH = DATA / "pharma_dasrl_monthly_result.json"
        NOTES_PATH = DATA / "pharma_fetch_notes.txt"
        INDEX_KEY = "NSE_INDEX|Nifty Pharma"
        INDEX_SYMBOL = "NIFTYPHARMA"
        LOOK_NOTE = (
            "Monthly weights on the mixed mid-and-small pharma book. Same ranker, "
            "reward constants, seed, and pre-2024 train cut. Weights are set when "
            "the names refresh and then held. Third look at the 2024-2026 window. "
            "Earlier pharma files are unchanged."
        )
        return
    if sector == "pharma-small":
        UNIVERSE = PHARMA_SMALL
        BARS_PATH = DATA / "pharma_bars.csv"
        INDEX_PATH = DATA / "nifty_pharma_index.csv"
        OUT_PATH = DATA / "pharma_smallcap_dasrl_result.json"
        NOTES_PATH = DATA / "pharma_fetch_notes.txt"
        INDEX_KEY = "NSE_INDEX|Nifty Pharma"
        INDEX_SYMBOL = "NIFTYPHARMA"
        LOOK_NOTE = (
            "First look at current Nifty Smallcap 250 drug makers, same frozen "
            "algo and the same 2024-2026 window. Midcap names are excluded. "
            "Not a refit of the earlier pharma prints."
        )
        return
    if sector == "power":
        UNIVERSE = POWER
        BARS_PATH = DATA / "power_bars.csv"
        INDEX_PATH = DATA / "power_index.csv"
        OUT_PATH = DATA / "power_dasrl_result.json"
        NOTES_PATH = DATA / "power_fetch_notes.txt"
        INDEX_KEY = ""
        INDEX_SYMBOL = ""
        return
    raise SystemExit("sector must be pharma, pharma-small, or power")


def public_result(result: dict) -> dict:
    out = dict(result)
    out.pop("daily", None)
    return out


def year_rows(daily) -> list[dict]:
    prev = CAPITAL
    latest = {}
    for day, equity, _ret in daily:
        latest[day.year] = (day, equity)
    rows = []
    for year in sorted(latest):
        day, equity = latest[year]
        rows.append({
            "year": year,
            "through": day.isoformat(),
            "return_before_tax": equity / prev - 1.0,
        })
        prev = equity
    return rows


def after_tax_yearly(end_equity: float, tax: float, sessions: int) -> dict:
    years = sessions / 252.0
    kept = end_equity - tax
    return {
        "years": years,
        "yearly_return_before_tax": (end_equity / CAPITAL) ** (1.0 / years) - 1.0,
        "yearly_return_after_tax": (kept / CAPITAL) ** (1.0 / years) - 1.0,
        "total_profit_after_tax": kept - CAPITAL,
        "average_profit_per_year": (kept - CAPITAL) / years,
    }


def run_weekly_nn(
    book, index, kept, dropped, rankings, train_end: int,
    out_path: Path | None = None, universe_note: str | None = None,
) -> None:
    """Train the weight network on pre-2024 weeks, then score 2018-2026. No refit.

    Rankings are rebuilt so a name enters in the week it becomes one year old.
    """
    del rankings
    for symbol, series in sorted(kept.items()):
        first = series.dates[0]
        if first <= date(2018, 1, 5):
            print(f"eligible {symbol} already listed", flush=True)
        else:
            print(f"eligible {symbol} from {add_year(first)} listed {first}", flush=True)
    rankings = {day: ranked_on(book, day, require_one_year=True) for day in book.dates}
    for symbol, series in sorted(kept.items()):
        if series.dates[0] <= date(2018, 1, 5):
            continue
        entered = next(
            (day for day in book.dates if symbol in [name for name, _ in rankings[day][:N_HOLD]]),
            None,
        )
        print(f"top3 {symbol} {entered}", flush=True)
    actor = train(book, index, train_end, rankings, rebalance_every="week")
    start_i = next(i for i, day in enumerate(book.dates) if len(rankings[day]) >= N_HOLD)
    result = simulate(
        book, index, make_ppo_policy(actor), start_i, len(book.dates), False, rankings,
        ignore_test_cut=True, rebalance_every="week",
    )
    stats = metrics(result["daily"])
    stats["costs"] = result["costs"]
    stats["tax"] = result["tax"]
    stats["net_profit"] = result["equity"] - CAPITAL - result["tax"]
    first_fill = book.dates[start_i + 1]
    alive = [symbol for symbol in kept if book.bar(symbol, first_fill) is not None]
    hold = buy_and_hold(book, alive, first_fill)
    pre = [row for row in result["daily"] if row[0] < TEST_START]
    post = [row for row in result["daily"] if row[0] >= TEST_START]
    pre_m = metrics(pre)
    base = pre[-1][1]
    post_ann = (post[-1][1] / base) ** (252.0 / len(post)) - 1.0
    summary = after_tax_yearly(result["equity"], result["tax"], stats["sessions"])
    hold_summary = after_tax_yearly(hold["end_equity"], hold["tax"], hold["sessions"])
    years = year_rows(result["daily"])
    hold_years = year_rows(hold["daily"])
    path = out_path or (DATA / "pharma_weekly_nn_2018_age1y_result.json")
    print("WEEKLY_NN", json.dumps(stats, default=str))
    print("YEARLY", json.dumps(summary, default=str))
    print("HOLD_YEARLY", json.dumps(hold_summary, default=str))
    print("YEARS", json.dumps(years, default=str))
    print("HOLD_YEARS", json.dumps(hold_years, default=str))
    print("pre_2024_yearly_before_tax", pre_m["annualized"], "from_2024_yearly_before_tax", post_ann)
    print("first_fill", first_fill, "last", result["daily"][-1][0])
    print("dropped", dropped)
    path.write_text(json.dumps({
        "book": "top 3, network weights, rotated once a week",
        "first_fill": first_fill,
        "last": result["daily"][-1][0],
        "universe": sorted(kept),
        "dropped": dropped,
        "weekly_nn": stats,
        "yearly": summary,
        "buy_hold_yearly": hold_summary,
        "years_before_tax": years,
        "hold_years_before_tax": hold_years,
        "before_2024_yearly_before_tax": pre_m["annualized"],
        "from_2024_yearly_before_tax": post_ann,
        "equity_at_2024_boundary": base,
        "assumptions": {
            "train": "Network trained only on sessions before 2024-01-01. Same seed, reward constants, 90-session ranker, and top 3. Not refit after this print.",
            "universe": universe_note or "Every drug maker in the Nifty MidSmall Healthcare list is eligible in the week its history reaches one year. Names whose file starts on 2018-01-01 were already listed. The book still holds three.",
            "in_sample": "2018-2023 on this path is the training period. It is not a test. 2024-2026 was already used in earlier pharma runs.",
            "rotation": "Names and weights are set at the close before the first session of each week, filled at that open, and held until the next week.",
            "tax": "FY 2026-27 rates applied to the whole path. The yearly after-tax return is the compound rate on end value minus that tax.",
        },
    }, indent=2, default=str))


def run_full_equal_weight(book, index, kept, dropped, rankings) -> None:
    """Frozen monthly equal-weight book from the first day three names can be scored."""
    start_i = next(i for i, day in enumerate(book.dates) if len(rankings[day]) >= N_HOLD)
    lim = simulate(
        book, index, equal_weight_policy, start_i, len(book.dates), False, rankings,
        ignore_test_cut=True,
    )
    lim_m = metrics(lim["daily"])
    lim_m["costs"] = lim["costs"]
    lim_m["tax"] = lim["tax"]
    lim_m["net_profit"] = lim["equity"] - CAPITAL - lim["tax"]
    first_fill = book.dates[start_i + 1]
    alive = [symbol for symbol in kept if book.bar(symbol, first_fill) is not None]
    hold = buy_and_hold(book, alive, first_fill)
    pre = [row for row in lim["daily"] if row[0] < TEST_START]
    post = [row for row in lim["daily"] if row[0] >= TEST_START]
    pre_m = metrics(pre)
    base = pre[-1][1]
    post_total = post[-1][1] / base - 1.0
    post_ann = (1.0 + post_total) ** (252.0 / len(post)) - 1.0
    path = DATA / "pharma_monthly_eq_2018_result.json"
    print("LIM", json.dumps(lim_m, default=str))
    print("HOLD", json.dumps(hold, default=str))
    print("pre_2024", json.dumps(pre_m, default=str))
    print("from_2024_pace", post_ann, "from_2024_end", post[-1][1], "boundary", base)
    print("first_fill", first_fill, "last", lim["daily"][-1][0])
    print("hold_names", sorted(alive))
    print("dropped", dropped)
    print("universe", sorted(kept))
    path.write_text(json.dumps({
        "book": "top 3 equal weight, set once a month",
        "first_fill": first_fill,
        "last": lim["daily"][-1][0],
        "universe": sorted(kept),
        "hold_names_on_first_fill": sorted(alive),
        "dropped": dropped,
        "lim_equal_weight": lim_m,
        "buy_hold": public_result(hold),
        "before_2024": pre_m,
        "from_2024_annualized_before_tax": post_ann,
        "equity_at_2024_boundary": base,
        "assumptions": {
            "no_refit": "Same 90-session ranker, top 3, monthly equal weight. No network. Constants were not changed after this print.",
            "window": "Bars from 2018. The first trade waits until 90 sessions exist. 2024-2026 was already scored, so this full path is not a new hidden test.",
            "tax": "FY 2026-27 rates applied to the whole path, including years when the statutory rates were different.",
            "costs": "The single Zerodha schedule from india-market-learnings.md, including years before that schedule.",
        },
    }, indent=2, default=str))


ALL_UNIVERSE_NOTE = (
    "Every current NSE pharma listing outside the Nifty 100, including names "
    "smaller than the smallcap index and trade-for-trade names. A name enters "
    "the ranker in the week it is one year old. Hospitals, diagnostics, devices, "
    "and Advanced Enzyme are out. Sun, Divi's, Torrent, Zydus, Cipla, and "
    "Dr Reddy's stay out. The book still holds three. Delisted names are absent."
)


def main():
    import sys
    configure(sys.argv[1] if len(sys.argv) > 1 else "pharma")
    mode = sys.argv[2] if len(sys.argv) > 2 else ""
    if mode in ("all", "signal"):
        global UNIVERSE, BARS_PATH, NOTES_PATH
        UNIVERSE = PHARMA_ALL
        BARS_PATH = DATA / "pharma_all_bars.csv"
        NOTES_PATH = DATA / "pharma_all_fetch_notes.txt"
        if mode == "all" or not BARS_PATH.exists():
            ensure_pharma_all_bars(load_token())
        if mode == "signal":
            refresh_latest_bars(load_token())
    if not BARS_PATH.exists():
        fetch_all(load_token())
    books = load_csv(BARS_PATH)
    books.pop(INDEX_SYMBOL, None)
    books = {symbol: series for symbol, series in books.items() if symbol in UNIVERSE}
    # The weekly run keeps later listings. They join the ranker in the week
    # they become one year old. The other runs still need a pre-2024 history.
    weekly = mode in ("weekly", "all", "signal")
    kept = {}
    dropped = []
    for symbol, series in books.items():
        if weekly or (series.dates[0] < TEST_START and series.dates[-1] >= TEST_START):
            kept[symbol] = series
        else:
            dropped.append(f"{symbol} {series.dates[0]} {series.dates[-1]}")
    book = Book(kept)
    if INDEX_PATH.exists() and INDEX_PATH.stat().st_size > 0:
        index_map = load_csv(INDEX_PATH)
        index = index_map.get("NIFTYPHARMA")
    else:
        index = None
    if index is None:
        # Equal-weight close of the pool, used only as the market feature.
        dates = book.dates
        closes = []
        for day in dates:
            prices = []
            for symbol, series in kept.items():
                loc = book.loc[symbol].get(day)
                if loc is not None:
                    prices.append(series.close[loc])
            closes.append(float(np.mean(prices)) if prices else np.nan)
        arr = np.array(closes)
        # Fill leading gaps then forward-fill.
        mask = np.isnan(arr)
        if mask.all():
            raise RuntimeError("no prices for a market feature")
        first = int(np.argmax(~mask))
        arr[:first] = arr[first]
        for i in range(first + 1, len(arr)):
            if np.isnan(arr[i]):
                arr[i] = arr[i - 1]
        index = Series(dates, arr, arr, arr, arr)
    train_end = next(i for i, day in enumerate(book.dates) if day >= TEST_START)
    test_start_i = max(0, train_end - 1)
    if mode == "weekly":
        run_weekly_nn(book, index, kept, dropped, {}, train_end)
        return
    if mode == "all":
        run_weekly_nn(
            book, index, kept, dropped, {}, train_end,
            out_path=DATA / "pharma_weekly_nn_2018_allpharma_result.json",
            universe_note=ALL_UNIVERSE_NOTE,
        )
        return
    if mode == "signal":
        run_signal(book, index, train_end)
        return
    rankings = {day: ranked_on(book, day) for day in book.dates}
    if mode == "full":
        run_full_equal_weight(book, index, kept, dropped, rankings)
        return
    lim = simulate(book, index, equal_weight_policy, test_start_i, len(book.dates), False, rankings)
    lim_m = metrics(lim["daily"])
    lim_m["costs"] = lim["costs"]
    lim_m["tax"] = lim["tax"]
    lim_m["net_profit"] = lim["equity"] - CAPITAL - lim["tax"]
    alive = [symbol for symbol in kept if book.bar(symbol, book.dates[train_end]) is not None]
    hold = buy_and_hold(book, alive, book.dates[train_end])
    print("LIM", json.dumps(lim_m, default=str))
    print("HOLD", json.dumps(hold, default=str))
    print("dropped", dropped)
    print("universe", sorted(kept))
    actor = train(book, index, train_end, rankings)
    ppo = simulate(book, index, make_ppo_policy(actor), test_start_i, len(book.dates), False, rankings)
    ppo_m = metrics(ppo["daily"])
    ppo_m["costs"] = ppo["costs"]
    ppo_m["tax"] = ppo["tax"]
    ppo_m["net_profit"] = ppo["equity"] - CAPITAL - ppo["tax"]
    print("PPO", json.dumps(ppo_m, default=str))
    OUT_PATH.write_text(json.dumps({
        "universe": sorted(kept),
        "dropped": dropped,
        "lim_equal_weight": lim_m,
        "buy_hold": public_result(hold),
        "ppo": ppo_m,
        "assumptions": {
            "reward_constants_not_in_paper": {
                "c_pos": C_POS, "c_neg": C_NEG, "c_step": C_STEP,
                "d_min": D_MIN, "horiz_cap": HORIZ_CAP, "end_bonus": END_BONUS,
            },
            "fills": "names and weights set at the close before the first session of the month, fill that open, held until the next month, no buy on the last session, sold at last test close",
            "costs": "Zerodha delivery from india-market-learnings.md: brokerage 0, STT 0.1% both sides, NSE 0.00307%, SEBI and IPFT Rs 10/crore, stamp 0.015% on the buy, GST 18% on exchange+SEBI only, DP Rs 15.34 inclusive once per symbol per sell day",
            "tax": "FY 2026-27. STCG 20% if held 12 months or less, including the anniversary. LTCG 12.5% above 1.25 lakh per FY after set-off. 4% cess. Deductible costs exclude STT. STCL offsets STCG then LTCG. LTCL offsets LTCG only. Carry forward 8 FYs. Tax is not taken from cash.",
            "not_applied": "Skip-month and a trend-to-cash filter are later changes in the note, and the note gives no trend rule. The NSE momentum clone was not substituted for this book. No F&O.",
            "look": LOOK_NOTE,
        },
    }, indent=2, default=str))


if __name__ == "__main__":
    main()
