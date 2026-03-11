"""
debug_data.py  —  SPY data comparison: Polygon vs Yahoo Finance

Run with:
    python scripts/debug_data.py

Fetches SPY for 2004-01-01 → today from both Polygon and Yahoo, then prints:
  - DataFrame length
  - Earliest / latest dates
  - First and last 3 rows
  - Closing-price range check for obvious truncation

This script is deliberately read-only and makes no changes to any cache or config.
"""

import os
import sys
from datetime import datetime

# ---- project root on path (scripts/ lives one level below the project root) ----
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

START = "2004-01-01"
END   = datetime.now().strftime("%Y-%m-%d")
SYMBOL = "SPY"

BASE_CONFIG = {
    "timeframe": "D",
    "timeframe_multiplier": 1,
    "price_adjustment": "total_return",
}


def _divider(label: str):
    width = 60
    print("\n" + "=" * width)
    print(f"  {label}")
    print("=" * width)


def _report(label: str, df):
    _divider(label)
    if df is None:
        print("  *** RESULT: None (fetch failed or no data) ***")
        return

    print(f"  Rows         : {len(df):,}")
    print(f"  Earliest bar : {df.index.min().date()}")
    print(f"  Latest bar   : {df.index.max().date()}")
    print(f"  Close range  : {df['Close'].min():.2f} – {df['Close'].max():.2f}")
    print(f"\n  First 3 rows:")
    print(df.head(3).to_string(max_cols=10))
    print(f"\n  Last 3 rows:")
    print(df.tail(3).to_string(max_cols=10))


# ---------------------------------------------------------------------------
# Polygon
# ---------------------------------------------------------------------------
_divider("POLYGON — fetching SPY")
try:
    from services.polygon_service import get_price_data as polygon_fetch
    polygon_df = polygon_fetch(SYMBOL, START, END, BASE_CONFIG)
    _report("POLYGON result", polygon_df)
except Exception as exc:
    print(f"  ERROR: {exc}")
    polygon_df = None


# ---------------------------------------------------------------------------
# Yahoo Finance
# ---------------------------------------------------------------------------
_divider("YAHOO — fetching SPY")
try:
    from services.yahoo_service import get_price_data as yahoo_fetch
    yahoo_df = yahoo_fetch(SYMBOL, START, END, BASE_CONFIG)
    _report("YAHOO result", yahoo_df)
except Exception as exc:
    print(f"  ERROR: {exc}")
    yahoo_df = None


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------
_divider("COMPARISON")

if polygon_df is not None and yahoo_df is not None:
    poly_len   = len(polygon_df)
    yahoo_len  = len(yahoo_df)
    poly_start = polygon_df.index.min().date()
    yahoo_start = yahoo_df.index.min().date()
    poly_end   = polygon_df.index.max().date()
    yahoo_end  = yahoo_df.index.max().date()

    print(f"  {'Metric':<25} {'Polygon':>15} {'Yahoo':>15}")
    print(f"  {'-'*55}")
    print(f"  {'Row count':<25} {poly_len:>15,} {yahoo_len:>15,}")
    print(f"  {'Earliest date':<25} {str(poly_start):>15} {str(yahoo_start):>15}")
    print(f"  {'Latest date':<25} {str(poly_end):>15} {str(yahoo_end):>15}")

    date_diff = abs((yahoo_start - poly_start).days)
    print(f"\n  Start-date gap  : {date_diff} calendar days "
          f"({'Yahoo earlier' if yahoo_start < poly_start else 'Polygon earlier'})")

    row_diff = yahoo_len - poly_len
    print(f"  Row count delta : {row_diff:+,} (positive = Yahoo has more bars)")

    if poly_len > 0 and yahoo_len > 0:
        poly_ret  = (polygon_df['Close'].iloc[-1] / polygon_df['Close'].iloc[0] - 1) * 100
        yahoo_ret = (yahoo_df['Close'].iloc[-1] / yahoo_df['Close'].iloc[0] - 1) * 100
        print(f"\n  Close-to-close return (full period loaded):")
        print(f"    Polygon : {poly_ret:+.1f}%")
        print(f"    Yahoo   : {yahoo_ret:+.1f}%")
        print(f"    Delta   : {yahoo_ret - poly_ret:+.1f} pp")
        print()
        print("  NOTE: If Yahoo return >> Polygon return, the most likely cause is")
        print("  that Polygon's history is truncated (e.g. API-plan bar limit).")
        print("  If returns are similar but start dates differ, it is purely a")
        print("  historical coverage difference between providers.")
elif polygon_df is None and yahoo_df is None:
    print("  Both fetches failed — check API keys and network.")
elif polygon_df is None:
    print("  Polygon fetch failed.  Yahoo data looks fine.")
else:
    print("  Yahoo fetch failed.  Polygon data looks fine.")

print()
