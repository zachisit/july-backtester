#!/usr/bin/env python3
"""Gross exposure at peak concurrency, from any trade log.

Answers "was this book levered" on dollars rather than on position count.
Count is the wrong instrument: with sizing at a fixed fraction of equity AT
ENTRY, positions opened at lower equity persist, so the count drifts above
1/allocation without any borrowing. The test is whether entry notional at peak
exceeds the equity available to fund it.

The equity floor is initial capital plus REALISED P&L only, ignoring unrealised
gains on the open book -- so the exposure ratio it produces is an upper bound.

Compute is separated from printing so the numbers can be asserted on directly.

Usage:
  python scripts/check_leverage.py <trade_log.csv> [--initial-capital 100000]
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

REQUIRED = ("EntryDate", "ExitDate", "Shares", "EntryPrice", "Profit")


def load_trades(csv_path: Path) -> pd.DataFrame:
    """Read a trade log, with an explicit guard on the columns this needs."""
    df = pd.read_csv(Path(csv_path))
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise KeyError(f"trade log missing required columns: {missing}")
    df = df.copy()
    df["EntryDate"] = pd.to_datetime(df["EntryDate"], errors="coerce")
    df["ExitDate"] = pd.to_datetime(df["ExitDate"], errors="coerce")
    for c in ("Shares", "EntryPrice", "Profit"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["Notional"] = df["Shares"] * df["EntryPrice"]
    return df.dropna(subset=["EntryDate"]).reset_index(drop=True)


def peak_exposure(df: pd.DataFrame, initial_capital: float = 100_000.0) -> dict:
    """Concurrency peak and the gross exposure carried at it.

    Events sort by (date, delta) so a close settles BEFORE an open on the same
    date -- sorting on date alone leaves same-day ties in arbitrary order and
    inflates the peak.
    """
    events = []
    for _, r in df.iterrows():
        events.append((r["EntryDate"], 1))
        if pd.notna(r["ExitDate"]):
            events.append((r["ExitDate"], -1))
    if not events:
        return {"peak_concurrency": 0, "peak_date": None, "open_positions": 0,
                "entry_notional": 0.0, "realized_to_date": 0.0,
                "equity_floor": initial_capital, "gross_exposure_pct": 0.0,
                "levered": False}

    ev = pd.DataFrame(events, columns=["date", "delta"]).sort_values(
        ["date", "delta"], kind="mergesort")
    ev["concurrent"] = ev["delta"].cumsum()
    peak_row = ev.loc[ev["concurrent"].idxmax()]
    peak_date = peak_row["date"]

    still_open = df["ExitDate"].isna() | (df["ExitDate"] > peak_date)
    op = df[(df["EntryDate"] <= peak_date) & still_open]
    notional = float(op["Notional"].sum())
    realized = float(df.loc[df["ExitDate"] <= peak_date, "Profit"].sum())
    floor = initial_capital + realized
    return {"peak_concurrency": int(peak_row["concurrent"]),
            "peak_date": peak_date,
            "open_positions": int(len(op)),
            "entry_notional": notional,
            "realized_to_date": realized,
            "equity_floor": floor,
            "gross_exposure_pct": (notional / floor * 100.0) if floor else float("inf"),
            "levered": notional > floor}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("trade_log", type=Path)
    ap.add_argument("--initial-capital", type=float, default=100_000.0)
    args = ap.parse_args()

    r = peak_exposure(load_trades(args.trade_log), args.initial_capital)
    d = r["peak_date"].date() if r["peak_date"] is not None else "n/a"
    print(f"\n  {args.trade_log}")
    print(f"  peak concurrency : {r['peak_concurrency']} on {d}")
    print(f"  open positions   : {r['open_positions']}")
    print(f"  entry notional   : ${r['entry_notional']:,.0f}")
    print(f"  realized to date : ${r['realized_to_date']:,.0f}")
    print(f"  equity floor     : ${r['equity_floor']:,.0f}"
          f"   (initial + realised only, so the ratio below is an upper bound)")
    print(f"  gross exposure   : {r['gross_exposure_pct']:.1f}% of equity floor")
    print(f"  VERDICT          : "
          f"{'EXCEEDS EQUITY - investigate' if r['levered'] else 'no leverage'}")
    print()


if __name__ == "__main__":
    main()
