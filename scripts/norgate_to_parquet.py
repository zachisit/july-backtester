#!/usr/bin/env python3
"""
norgate_to_parquet.py — Export Norgate bar data to Parquet files
================================================================

Uses the project's existing Norgate wrapper (services/norgate_service.py)
to iterate over all stocks in a Norgate watchlist and export daily OHLCV
bars to individual Parquet files.

Requirements:
    - Norgate Data Updater installed and running (Windows/macOS)
    - pip install norgatedata pyarrow pandas

Usage:
    # Export all stocks in the "Russell 3000" watchlist:
    python scripts/norgate_to_parquet.py --watchlist "Russell 3000"

    # Export specific tickers:
    python scripts/norgate_to_parquet.py --tickers AAPL MSFT GOOGL

    # Export to a specific directory:
    python scripts/norgate_to_parquet.py --watchlist "Nasdaq 100" --output-dir ./parquet_data

    # Resume a previously interrupted export (skips existing files):
    python scripts/norgate_to_parquet.py --watchlist "Russell 3000" --skip-existing

    # Export hourly bars:
    python scripts/norgate_to_parquet.py --watchlist "Nasdaq 100" --timeframe H

    # Export 5-minute bars:
    python scripts/norgate_to_parquet.py --tickers AAPL --timeframe MIN --multiplier 5

Output:
    One Parquet file per symbol in the output directory:
        parquet_data/AAPL.parquet
        parquet_data/MSFT.parquet
        ...

    Each file has columns: Open, High, Low, Close, Volume
    with a DatetimeIndex.

    Symbols containing illegal filename characters (e.g. I:VIX) are
    sanitized: colons and other special characters become underscores
    (I:VIX → I_VIX.parquet).
"""

import argparse
import logging
import os
import sys
import time
from pathlib import Path

# Add project root to sys.path so we can import from services/
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# ---------------------------------------------------------------------------
# Set up logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Characters illegal in Windows filenames (and generally problematic on any OS)
_ILLEGAL_FILENAME_CHARS = r'\/:*?"<>|'


def _sanitize_filename(symbol: str) -> str:
    """Replace characters that are illegal in Windows filenames with underscores."""
    for ch in _ILLEGAL_FILENAME_CHARS:
        symbol = symbol.replace(ch, "_")
    return symbol


def get_watchlist_symbols(watchlist_name: str) -> list[str]:
    """Fetch all symbols from a Norgate watchlist."""
    import norgatedata
    symbols = norgatedata.watchlist_symbols(watchlist_name)
    if not symbols:
        logger.warning(f"Watchlist '{watchlist_name}' returned 0 symbols.")
    return symbols


def export_symbol(symbol: str, output_dir: Path, config: dict, skip_existing: bool = False) -> bool:
    """
    Export a single symbol's daily bars to a Parquet file using the
    existing norgate_service.py wrapper.

    Returns True if the file was written (or already existed), False on error.
    """
    from services.norgate_service import get_price_data

    output_path = output_dir / f"{_sanitize_filename(symbol)}.parquet"

    if skip_existing and output_path.exists():
        return True

    try:
        df = get_price_data(
            symbol,
            start_date=config["start_date"],
            end_date=config["end_date"],
            config=config,
        )

        if df is None or df.empty:
            logger.warning(f"  {symbol}: no data returned, skipping")
            return False

        # Ensure only OHLCV columns are saved
        keep_cols = ["Open", "High", "Low", "Close", "Volume"]
        available = [c for c in keep_cols if c in df.columns]
        df = df[available]

        df.to_parquet(output_path, engine="pyarrow")
        return True

    except Exception as e:
        logger.error(f"  {symbol}: ERROR — {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Export Norgate bar data to Parquet files for the july-backtester."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--watchlist", type=str,
        help='Norgate watchlist name (e.g., "Russell 3000", "Nasdaq 100")',
    )
    group.add_argument(
        "--tickers", nargs="+", type=str,
        help="One or more ticker symbols to export",
    )
    parser.add_argument(
        "--output-dir", type=str, default="parquet_data",
        help="Directory for output Parquet files (default: parquet_data/)",
    )
    parser.add_argument(
        "--skip-existing", action="store_true",
        help="Skip symbols that already have a Parquet file in the output dir",
    )
    parser.add_argument(
        "--start-date", type=str, default="2000-01-01",
        help="Start date for data export (default: 2000-01-01)",
    )
    parser.add_argument(
        "--end-date", type=str, default=None,
        help="End date for data export (default: today)",
    )
    parser.add_argument(
        "--timeframe", type=str, choices=["D", "H", "MIN"], default="D",
        help="Bar timeframe: D=daily (default), H=hourly, MIN=minute",
    )
    parser.add_argument(
        "--multiplier", type=int, default=1,
        help="Timeframe multiplier (e.g. 5 for 5-minute bars, default: 1)",
    )

    args = parser.parse_args()

    # --- Validate norgatedata is available ---
    try:
        import norgatedata
    except ImportError:
        logger.error(
            "norgatedata package not found. Install it with:\n"
            "  pip install norgatedata\n"
            "and ensure the Norgate Data Updater is running."
        )
        sys.exit(1)

    # --- Build a config dict matching what norgate_service.py expects ---
    from datetime import datetime

    end_date = args.end_date or datetime.now().strftime("%Y-%m-%d")

    config = {
        "data_provider": "norgate",
        "start_date": args.start_date,
        "end_date": end_date,
        "timeframe": args.timeframe,
        "timeframe_multiplier": args.multiplier,
        "price_adjustment": norgatedata.StockPriceAdjustmentType.TOTALRETURN,
    }

    # --- Get the symbol list ---
    if args.watchlist:
        logger.info(f"Fetching symbols from watchlist: '{args.watchlist}'")
        symbols = get_watchlist_symbols(args.watchlist)
    else:
        symbols = args.tickers

    if not symbols:
        logger.error("No symbols to export. Exiting.")
        sys.exit(1)

    logger.info(f"Exporting {len(symbols)} symbols to {args.output_dir}/")
    logger.info(f"Date range: {args.start_date} -> {end_date}")

    # --- Create output directory ---
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # --- Export loop with progress ---
    success_count = 0
    fail_count = 0
    skip_count = 0
    start_time = time.time()

    for i, symbol in enumerate(symbols, 1):
        if args.skip_existing and (output_dir / f"{_sanitize_filename(symbol)}.parquet").exists():
            skip_count += 1
            continue

        ok = export_symbol(symbol, output_dir, config, skip_existing=args.skip_existing)

        if ok:
            success_count += 1
        else:
            fail_count += 1

        # Log progress every 50 symbols
        if i % 50 == 0:
            elapsed = time.time() - start_time
            rate = i / elapsed if elapsed > 0 else 0
            eta = (len(symbols) - i) / rate if rate > 0 else 0
            logger.info(
                f"  Progress: {i}/{len(symbols)} "
                f"({success_count} ok, {fail_count} failed, {skip_count} skipped) "
                f"— ETA: {eta:.0f}s"
            )

    elapsed = time.time() - start_time
    logger.info(
        f"\nDone in {elapsed:.1f}s — "
        f"{success_count} exported, {fail_count} failed, {skip_count} skipped"
    )
    logger.info(f"Output directory: {output_dir.resolve()}")


if __name__ == "__main__":
    main()
