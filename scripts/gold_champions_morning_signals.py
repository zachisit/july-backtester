"""One-shot diagnostic: run the three gold-regime sleeves on fresh yfinance
data and report what signals they would have produced for the morning open.

Run:  rtk .venv/bin/python scripts/gold_champions_morning_signals.py
"""
import os
import sys
import warnings
from datetime import datetime

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

R21_BASKET = ["GLD", "GDX", "GOLD", "NEM", "WPM", "RGLD", "AEM", "FNV"]
EC_ENERGY_BASKET = ["XOM", "CVX", "COP", "EOG", "OXY", "PSX", "VLO", "MPC",
                    "SLB", "DVN", "FANG", "BKR", "XLE", "XOP"]
DEFENSIVE_BASKET = ["TLT", "GLD"]

START = "2024-01-01"
# Trim to yesterday (avoid pulling intraday partial bar for today).
YESTERDAY = (pd.Timestamp.now().normalize() - pd.Timedelta(days=1))


def _yf_close(symbol: str) -> pd.Series:
    import yfinance as yf
    df = yf.Ticker(symbol).history(start=START, end=YESTERDAY + pd.Timedelta(days=1),
                                   auto_adjust=False)
    if df.empty:
        return pd.Series(dtype=float, name=symbol)
    s = df["Close"].copy()
    s.index = s.index.tz_localize(None)
    s = s[s.index <= YESTERDAY]
    s.name = symbol
    return s


def _yf_ohlcv(symbol: str) -> pd.DataFrame:
    import yfinance as yf
    df = yf.Ticker(symbol).history(start=START, end=YESTERDAY + pd.Timedelta(days=1),
                                   auto_adjust=False)
    if df.empty:
        return pd.DataFrame()
    df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
    df.index = df.index.tz_localize(None)
    df = df[df.index <= YESTERDAY]
    return df


def _rolling_sma(s, n):
    return s.rolling(n, min_periods=n).mean()


def _williams_r(df, n):
    high = df["High"].rolling(n).max()
    low = df["Low"].rolling(n).min()
    return -100.0 * (high - df["Close"]) / (high - low).replace(0, np.nan)


def r21_signals(df: pd.DataFrame, vix: pd.Series, spy: pd.Series, tlt: pd.Series,
                sma_len=50, spy_sma_long=200, vix_calm=30.0,
                tnx_panic_window=20, tnx_panic_drop_tlt=-0.08) -> pd.DataFrame:
    """Original (TLT-wired) gr_a09_tnx_panic_exit — exact port from
    custom_strategies/private/gold_tactical_strategies.py."""
    out = df.copy()
    sma = _rolling_sma(out["Close"], sma_len)
    above_sma = (out["Close"] > sma).fillna(False)

    v = vix.reindex(out.index, method="ffill").fillna(20.0)
    sp = spy.reindex(out.index, method="ffill").ffill()
    sp_sma = sp.rolling(spy_sma_long, min_periods=spy_sma_long).mean()
    tl = tlt.reindex(out.index, method="ffill").ffill()

    vix_ok = (v < vix_calm).fillna(False)
    spy_ok = (sp > sp_sma).fillna(False)
    regime = vix_ok | spy_ok

    tlt_ret = tl.pct_change(tnx_panic_window)
    rate_shock = (tlt_ret < tnx_panic_drop_tlt).fillna(False)

    sig = pd.Series(-1, index=out.index)
    sig[above_sma & regime & ~rate_shock] = 1
    sig[(~above_sma) | rate_shock] = -1
    out["Signal"] = sig
    return out[["Close", "Signal"]]


def ecvix27_signals(df: pd.DataFrame, vix: pd.Series,
                    wr_length=70, entry_normal=-20.0, entry_extreme=-25.0,
                    exit_normal=-80.0, exit_elevated=-65.0, exit_extreme=-45.0,
                    vix_extreme=0.95, vix_window=252, sma_slow=120) -> pd.DataFrame:
    out = df.copy()
    wr = _williams_r(out, wr_length)
    sma = _rolling_sma(out["Close"], sma_slow)
    above = (out["Close"] >= sma).fillna(False)

    v = vix.reindex(out.index, method="ffill").fillna(15.0)
    vix_pct = v.rolling(vix_window).rank(pct=True).fillna(0.0)

    signals = []
    in_pos = False
    prev_above_entry = False
    for i in range(len(out)):
        wr_v, sma_v = wr.iloc[i], sma.iloc[i]
        if pd.isna(wr_v) or pd.isna(sma_v):
            signals.append(-1)
            in_pos = False
            prev_above_entry = False
            continue

        pct = float(vix_pct.iloc[i])
        if pct > vix_extreme:
            ent, ex = entry_extreme, exit_extreme
        elif pct > 0.50:
            ent, ex = entry_normal, exit_elevated
        else:
            ent, ex = entry_normal, exit_normal

        cur_above_entry = float(wr_v) > ent
        cross_up = cur_above_entry and not prev_above_entry
        is_entry = cross_up and bool(above.iloc[i])
        is_exit = (float(wr_v) < ex) or (not above.iloc[i])

        if not in_pos:
            if is_entry:
                signals.append(1); in_pos = True
            else:
                signals.append(-1)
        else:
            if is_exit:
                signals.append(-1); in_pos = False
            else:
                signals.append(1)
        prev_above_entry = cur_above_entry

    out["Signal"] = signals
    return out[["Close", "Signal"]]


def universal_def_signals(df: pd.DataFrame, vix: pd.Series, spy: pd.Series,
                          vix_stress=35.0, spy_sma_long=200) -> pd.DataFrame:
    out = df.copy()
    v = vix.reindex(out.index, method="ffill").fillna(20.0)
    sp = spy.reindex(out.index, method="ffill").ffill()
    sp_sma = sp.rolling(spy_sma_long, min_periods=spy_sma_long).mean()
    stress = ((v > vix_stress) | (sp < sp_sma)).fillna(False)
    sig = pd.Series(-1, index=out.index)
    sig[stress] = 1
    out["Signal"] = sig
    return out[["Close", "Signal"]]


def _bar(width=78):
    return "─" * width


def main():
    print(_bar())
    print(f"  GOLD-REGIME CHAMPIONS — MORNING SIGNAL CHECK  ({datetime.now():%Y-%m-%d %H:%M})")
    print(_bar())

    # Macro context
    print("\nFetching macro context (SPY, ^VIX, TLT, ^TNX) ...")
    spy = _yf_close("SPY")
    vix = _yf_close("^VIX")
    tlt = _yf_close("TLT")
    tnx = _yf_close("^TNX")
    last_date = max(spy.index[-1], vix.index[-1])

    spy_sma200 = spy.rolling(200, min_periods=200).mean()
    tlt_20d = tlt.pct_change(20)
    tnx_20d = tnx.pct_change(20)

    print(f"\n  Latest bar: {last_date.date()}")
    print(f"  SPY:        {spy.iloc[-1]:8.2f}   vs SMA200 ({spy_sma200.iloc[-1]:.2f}): "
          f"{'ABOVE' if spy.iloc[-1] > spy_sma200.iloc[-1] else 'BELOW'}")
    print(f"  ^VIX:       {vix.iloc[-1]:8.2f}   {'<' if vix.iloc[-1] < 30 else '>='} 30 (calm gate)   "
          f"{'<' if vix.iloc[-1] < 35 else '>='} 35 (stress gate)")
    print(f"  TLT:        {tlt.iloc[-1]:8.2f}   20d return: {tlt_20d.iloc[-1]:+.2%}   "
          f"({'RATE SHOCK' if tlt_20d.iloc[-1] < -0.08 else 'no rate shock'})")
    print(f"  ^TNX:       {tnx.iloc[-1]:8.2f}   20d return: {tnx_20d.iloc[-1]:+.2%}   "
          f"({'YIELDS SURGING' if tnx_20d.iloc[-1] > 0.08 else 'no yield surge'})")

    def _run_basket(name: str, tickers: list[str], strategy_fn, ticker_arg_label="symbol"):
        print(f"\n{_bar()}")
        print(f"  {name}")
        print(_bar())
        rows = []
        for sym in tickers:
            ohlcv = _yf_ohlcv(sym)
            if ohlcv.empty or len(ohlcv) < 260:
                rows.append((sym, "N/A", "N/A", "no data / short history"))
                continue
            sigs = strategy_fn(ohlcv)
            today = int(sigs["Signal"].iloc[-1])
            yest = int(sigs["Signal"].iloc[-2])
            note = ""
            if yest != today:
                note = f"TRANSITION  {yest:+d} → {today:+d}"
            elif today == 1:
                note = "long (hold)"
            else:
                note = "flat (no position)"
            rows.append((sym, today, yest, note))
        # print
        print(f"  {'Ticker':<8}  {'Yest':>5}  {'Today':>6}  Status")
        for sym, today, yest, note in rows:
            t_str = f"{today:+d}" if isinstance(today, int) else "N/A"
            y_str = f"{yest:+d}" if isinstance(yest, int) else "N/A"
            print(f"  {sym:<8}  {y_str:>5}  {t_str:>6}  {note}")

    # Strategy 1: GOLD-R21 Tactical
    _run_basket(
        "GOLD-R21 Tactical (8-name gold-equity basket)",
        R21_BASKET,
        lambda df: r21_signals(df, vix=vix, spy=spy, tlt=tlt),
    )

    # Strategy 2: GOLD-EC-VIX-27
    _run_basket(
        "GOLD-EC-VIX-27 (14-name energy basket)",
        EC_ENERGY_BASKET,
        lambda df: ecvix27_signals(df, vix=vix),
    )

    # Strategy 3: GOLD-UNIVERSAL-DEFENSIVE
    _run_basket(
        "GOLD-UNIVERSAL-DEFENSIVE (TLT + GLD)",
        DEFENSIVE_BASKET,
        lambda df: universal_def_signals(df, vix=vix, spy=spy),
    )

    print(f"\n{_bar()}")
    print("  LEGEND")
    print(_bar())
    print("  Signal  +1 = long (hold)         -1 = flat / exit")
    print("  TRANSITION  -1 → +1 = buy signal at next open")
    print("  TRANSITION  +1 → -1 = sell signal at next open")
    print()


if __name__ == "__main__":
    main()
