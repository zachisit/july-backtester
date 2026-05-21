"""Pad an equity CSV with flat $100k from 1990-01-02 until its first real
date. This is the right way to combine a sleeve whose underlying instrument
didn't exist pre-2002 with a longer-period equity curve: the sleeve simply
held cash before its instrument was tradable.

Usage:
    python scripts/pad_equity_to_1990.py <in_csv> <out_csv>
"""

import sys
from pathlib import Path

import pandas as pd


def main():
    if len(sys.argv) < 3:
        print("Usage: python scripts/pad_equity_to_1990.py <in_csv> <out_csv>")
        sys.exit(2)

    in_csv = Path(sys.argv[1])
    out_csv = Path(sys.argv[2])

    df = pd.read_csv(in_csv, parse_dates=["Date"]).set_index("Date").sort_index()
    df.index = df.index.tz_localize(None) if df.index.tz else df.index

    start_val = df.iloc[0]["Equity"]

    # Use SPY parquet's index as the "calendar" for padding (US trading days)
    spy_path = Path("/Users/zach/Desktop/github/july-backtester/parquet_data/data/SPY.parquet")
    spy = pd.read_parquet(spy_path)
    spy.index = spy.index.tz_localize(None) if spy.index.tz else spy.index
    # Find trading days from 1993 (SPY parquet start) up to df's first date
    first_real_date = df.index.min()
    pad_dates = spy.index[(spy.index < first_real_date)]

    if len(pad_dates) == 0:
        # Nothing to pad
        df.to_csv(out_csv)
        print(f"No padding needed (data starts at {first_real_date.date()}). Copied to {out_csv}")
        return

    pad = pd.DataFrame({"Equity": [start_val] * len(pad_dates)}, index=pad_dates)
    pad.index.name = "Date"

    combined = pd.concat([pad, df]).sort_index()
    # Drop any duplicate index entries
    combined = combined[~combined.index.duplicated(keep="last")]

    combined.to_csv(out_csv)

    print(f"Wrote {out_csv}")
    print(f"  Padded {len(pad_dates)} bars at flat ${start_val:.0f}")
    print(f"  Full range: {combined.index.min().date()} → {combined.index.max().date()}  ({len(combined)} bars)")


if __name__ == "__main__":
    main()
