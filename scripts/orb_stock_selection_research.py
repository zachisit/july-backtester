"""ORB stock-selection research — faithful port of the Zarattini/Barbon/Aziz (2024)
"A Profitable Day Trading Strategy For The U.S. Equity Market" opening-range-breakout.

Stage 1 (this run): the daily "stocks in play" SCREEN, look-ahead-free.
  Each session, within a liquid high-beta universe, keep names passing liquidity
  filters (price, ADV, ATR) and rank by |gap%| at the open (gappers = in play).
  Take the top-N. Output selection stats to bound the intraday 5-min fetch (Stage 2).

Why gap-magnitude for the screen: relative volume on the *full* day's volume is
look-ahead (you can't know EOD volume at 09:30). Gap = open/prev_close-1 is known
at the open. First-5-min relative volume (also look-ahead-free) is layered in at
entry time in Stage 2, not here.

Run: rtk .venv/bin/python scripts/orb_stock_selection_research.py
"""

import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from config import CONFIG
from services.polygon_service import get_price_data

# --- Screen parameters (Zarattini-style liquidity filters) ---
UNIVERSE_FILE = "tickers_to_scan/high_volatility.json"
MIN_PRICE = 5.0            # price > $5
MIN_ADV = 1_000_000        # 20d avg daily volume > 1M shares
ATR_LEN = 14
ADV_LEN = 20
TOP_N_PER_DAY = 20         # "stocks in play" kept each session
# Intraday 5-min data on this Polygon plan starts ~2021-07-12; screen the same window.
SCREEN_START = "2021-06-01"   # ~6wk lookback pad before intraday window for ADV/ATR
SCREEN_END = "2026-06-15"
INTRADAY_AVAILABLE_FROM = "2021-07-12"


def _fetch_daily(sym):
    cfg = dict(CONFIG)
    cfg["timeframe"] = "D"
    cfg["timeframe_multiplier"] = 1
    try:
        df = get_price_data(sym, SCREEN_START, SCREEN_END, cfg)
        if df is None or df.empty:
            return None
        return df[["Open", "High", "Low", "Close", "Volume"]].copy()
    except Exception as e:
        print(f"  fetch err {sym}: {str(e)[:60]}")
        return None


def _atr(df, n=ATR_LEN):
    h, l, c = df["High"], df["Low"], df["Close"]
    pc = c.shift(1)
    tr = pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(n, min_periods=n).mean()


def main():
    universe = json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), UNIVERSE_FILE)))
    print(f"Universe: {len(universe)} names from {UNIVERSE_FILE}")
    print(f"Screening {SCREEN_START} -> {SCREEN_END} (intraday available from {INTRADAY_AVAILABLE_FROM})\n")

    # Build a per-day, per-symbol frame of the screen inputs.
    rows = []
    n_ok = 0
    for i, sym in enumerate(universe):
        df = _fetch_daily(sym)
        if df is None or len(df) < ADV_LEN + 2:
            continue
        n_ok += 1
        df = df.sort_index()
        df["adv"] = df["Volume"].rolling(ADV_LEN, min_periods=ADV_LEN).mean().shift(1)  # prior ADV (no look-ahead)
        df["atr"] = _atr(df).shift(1)                                                    # prior ATR (no look-ahead)
        df["prev_close"] = df["Close"].shift(1)
        df["gap_pct"] = (df["Open"] - df["prev_close"]) / df["prev_close"]
        df["atr_pct"] = df["atr"] / df["Open"]
        for ts, r in df.iterrows():
            rows.append((ts.normalize(), sym, r["Open"], r["adv"], r["atr_pct"], r["gap_pct"]))
        if (i + 1) % 40 == 0:
            print(f"  fetched {i+1}/{len(universe)} ({n_ok} usable)...")

    panel = pd.DataFrame(rows, columns=["date", "sym", "open", "adv", "atr_pct", "gap_pct"]).dropna()
    _cut = pd.Timestamp(INTRADAY_AVAILABLE_FROM, tz="UTC").normalize()
    if panel["date"].dt.tz is None:
        _cut = _cut.tz_localize(None)
    panel = panel[panel["date"] >= _cut]
    print(f"\nUsable names: {n_ok}/{len(universe)} | screenable stock-days: {len(panel):,}")

    # Liquidity filters, then rank by |gap%| and keep top-N per day.
    liq = panel[(panel["open"] > MIN_PRICE) & (panel["adv"] > MIN_ADV)].copy()
    liq["abs_gap"] = liq["gap_pct"].abs()
    picks = (liq.sort_values(["date", "abs_gap"], ascending=[True, False])
                .groupby("date").head(TOP_N_PER_DAY))

    n_days = picks["date"].nunique()
    uniq = picks["sym"].nunique()
    freq = picks["sym"].value_counts()
    avg_gap = picks["abs_gap"].mean()
    print(f"\n=== SCREEN RESULT ===")
    print(f"Sessions screened: {n_days}")
    print(f"Avg picks/session: {len(picks)/n_days:.1f} (target {TOP_N_PER_DAY})")
    print(f"Unique names ever selected: {uniq}  <-- Stage-2 intraday fetch scope")
    print(f"Median |gap%| of picks: {picks['abs_gap'].median()*100:.2f}%  |  mean {avg_gap*100:.2f}%")
    print(f"\nTop 20 most-selected names:")
    for s, c in freq.head(20).items():
        print(f"  {s:6s} {c:4d} sessions ({c/n_days*100:4.1f}% of days)")

    # Persist the selection set for Stage 2.
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "orb_selection_stage1.csv")
    picks.to_csv(out, index=False)
    print(f"\nWrote selections -> {out}")
    print(f"Unique-name list ({uniq}) -> stage-2 will fetch 5-min bars for these.")


if __name__ == "__main__":
    main()
