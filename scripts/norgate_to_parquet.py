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

Output:
    One Parquet file per symbol in the output directory:
        parquet_data/AAPL.parquet
        parquet_data/MSFT.parquet
        ...

    Each file has columns: Open, High, Low, Close, Volume
    with a DatetimeIndex.
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


def get_watchlist_symbols(watchlist_name: str) -> list[str]:
    """Fetch all symbols from a Norgate watchlist."""
    import norgatedata
    symbols = norgatedata.watchlist_symbols(watchlist_name)
    if not symbols:
        logger.warning(f"Watchlist '{watchlist_name}' returned 0 symbols.")
    return symbols


# Canonical OHLCV columns to export
_OHLCV_COLUMNS = ["Open", "High", "Low", "Close", "Volume"]


def export_symbol(symbol: str, output_dir: Path, config: dict, skip_existing: bool = False) -> bool:
    """
    Export a single symbol's daily bars to a Parquet file using the
    existing norgate_service.py wrapper.

    Returns True if the file was written (or already existed), False on error.
    """
    from services.norgate_service import get_price_data

    output_path = output_dir / f"{symbol}.parquet"

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
        available = [c for c in _OHLCV_COLUMNS if c in df.columns]
        df = df[available]

        # Atomic write: write to temp file first, then rename
        temp_path = output_dir / f"{symbol}.parquet.tmp"
        df.to_parquet(temp_path, engine="pyarrow")
        temp_path.rename(output_path)  # Atomic on most filesystems
        return True

    except Exception as e:
        logger.error(f"  {symbol}: ERROR — {e}")
        # Clean up temp file if it exists
        temp_path = output_dir / f"{symbol}.parquet.tmp"
        if temp_path.exists():
            temp_path.unlink()
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

    # --- Validate date formats ---
    from datetime import datetime

    try:
        datetime.strptime(args.start_date, "%Y-%m-%d")
        if args.end_date:
            datetime.strptime(args.end_date, "%Y-%m-%d")
    except ValueError as e:
        logger.error(f"Invalid date format: {e}. Use YYYY-MM-DD")
        sys.exit(1)

    end_date = args.end_date or datetime.now().strftime("%Y-%m-%d")

    config = {
        "data_provider": "norgate",
        "start_date": args.start_date,
        "end_date": end_date,
        "timeframe": "D",
        "timeframe_multiplier": 1,
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

    # --- Pre-flight validation ---
    # Test write access
    try:
        test_file = output_dir / ".write_test"
        test_file.touch()
        test_file.unlink()
    except Exception as e:
        logger.error(f"Output directory {output_dir} is not writable: {e}")
        sys.exit(1)

    # Warn if low disk space (rough estimate: 100KB per symbol for daily data)
    try:
        import shutil
        stat = shutil.disk_usage(output_dir)
        free_gb = stat.free / (1024 ** 3)
        required_gb = len(symbols) * 0.0001  # 100KB per symbol
        if free_gb < required_gb:
            logger.warning(
                f"Low disk space: {free_gb:.2f} GB free, "
                f"estimated need: {required_gb:.2f} GB"
            )
    except Exception:
        pass  # Non-critical, continue anyway

    # --- Export loop with progress ---
    success_count = 0
    fail_count = 0
    skip_count = 0
    failed_symbols = []
    start_time = time.time()

    # Determine progress logging interval (more frequent for small lists)
    log_interval = min(50, max(10, len(symbols) // 10))

    for i, symbol in enumerate(symbols, 1):
        if args.skip_existing and (output_dir / f"{symbol}.parquet").exists():
            skip_count += 1
            continue

        ok = export_symbol(symbol, output_dir, config, skip_existing=args.skip_existing)

        if ok:
            success_count += 1
        else:
            fail_count += 1
            failed_symbols.append(symbol)

        # Log progress at intervals
        if i % log_interval == 0 or i == len(symbols):
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

    # Report failed symbols if any
    if failed_symbols:
        logger.warning(f"\nFailed symbols ({len(failed_symbols)}):")
        # Show first 20, then truncate
        for sym in failed_symbols[:20]:
            logger.warning(f"  {sym}")
        if len(failed_symbols) > 20:
            logger.warning(f"  ... and {len(failed_symbols) - 20} more")


if __name__ == "__main__":
    main()
