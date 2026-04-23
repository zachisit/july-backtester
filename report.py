"""
Command-line script to generate detailed PDF/Markdown reports from backtester CSVs.

Usage:
    python report.py path/to/strategy.csv
    python report.py output/runs/2026-03-02_14-00-00/analyzer_csvs/Nasdaq_100/EMA_Regime.csv
    python report.py --all output/runs/2026-03-02_14-00-00
"""
import argparse
import json
import os
import sys
from pathlib import Path

import pandas as pd

from trade_analyzer.default_config import (
    BASE_OUTPUT_DIRECTORY,
    INITIAL_EQUITY,
    BENCHMARK_TICKER,
    RISK_FREE_RATE,
    TRADING_DAYS_PER_YEAR,
    ROLLING_WINDOW,
    TOP_N_LOSING_SYMBOLS,
    PROFITABLE_PF_THRESHOLD,
    UNPROFITABLE_PF_THRESHOLD,
    TOP_N_TRADES_LIST,
    MC_SIMULATIONS,
    MC_USE_PERCENTAGE_RETURNS,
    MC_DRAWDOWN_AS_NEGATIVE,
    MC_PERCENTILES,
    MARKDOWN_IMAGE_SUBDIR,
    MARKDOWN_PLOT_FORMAT,
    LINES_PER_TEXT_PAGE,
    A4_LANDSCAPE,
    MAX_XTICKS_BEFORE_RESIZE,
    VERBOSE_DEBUG,
    CRITICAL_COLS,
    NUMERIC_COLS,
    WFA_SPLIT_RATIO,
)
from trade_analyzer.analyzer import generate_trade_report


def _load_equity_file(path: Path) -> "pd.Series | None":
    """Load a companion _equity.csv as a date-indexed Series, or return None."""
    if not path.is_file():
        return None
    try:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        if df.empty:
            return None
        return df.iloc[:, 0].rename("Equity")
    except Exception:
        return None


def _load_wfa_split_ratio(run_dir: Path) -> float | None:
    """Read wfa_split_ratio from config_snapshot.json in a run directory.

    Returns the ratio (float) if present and valid (0 < ratio < 1),
    or None if the file is missing, the key is absent, or the value is invalid.
    """
    snapshot_path = run_dir / "config_snapshot.json"
    if not snapshot_path.is_file():
        return None
    try:
        with open(snapshot_path, "r", encoding="utf-8") as fh:
            snapshot = json.load(fh)
        ratio = snapshot.get("wfa_split_ratio")
        if ratio is not None and 0 < float(ratio) < 1:
            return float(ratio)
    except (json.JSONDecodeError, ValueError, TypeError):
        pass
    return None


def main():
    parser = argparse.ArgumentParser(
        description="Generate a detailed PDF/Markdown trade analysis report from a CSV file."
    )

    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        "csv_path",
        nargs="?",
        help="Path to a single backtester-generated CSV file.",
    )
    input_group.add_argument(
        "--all",
        type=str,
        metavar="RUN_DIR",
        help="Path to a run directory (e.g. output/runs/2026-03-02_15-12-32). Generates reports for all CSVs found under analyzer_csvs/.",
    )

    parser.add_argument(
        "--output-dir",
        default=None,
        help="Root directory for report output. Auto-detected from the CSV path when inside output/runs/<run_id>/analyzer_csvs/.",
    )
    parser.add_argument(
        "--equity",
        type=float,
        default=INITIAL_EQUITY,
        help=f"Initial equity for the analysis (default: {INITIAL_EQUITY}).",
    )
    parser.add_argument(
        "--report-name",
        type=str,
        default=None,
        help="Custom name for the generated PDF/Markdown report and its parent folder. If not provided, the CSV filename will be used.",
    )
    args = parser.parse_args()

    # Base config shared across both modes (BASE_OUTPUT_DIRECTORY set per mode below)
    base_config = {
        'INITIAL_EQUITY': args.equity,
        'BENCHMARK_TICKER': BENCHMARK_TICKER,
        'RISK_FREE_RATE': RISK_FREE_RATE,
        'TRADING_DAYS_PER_YEAR': TRADING_DAYS_PER_YEAR,
        'ROLLING_WINDOW': ROLLING_WINDOW,
        'TOP_N_LOSING_SYMBOLS': TOP_N_LOSING_SYMBOLS,
        'PROFITABLE_PF_THRESHOLD': PROFITABLE_PF_THRESHOLD,
        'UNPROFITABLE_PF_THRESHOLD': UNPROFITABLE_PF_THRESHOLD,
        'TOP_N_TRADES_LIST': TOP_N_TRADES_LIST,
        'MC_SIMULATIONS': MC_SIMULATIONS,
        'MC_USE_PERCENTAGE_RETURNS': MC_USE_PERCENTAGE_RETURNS,
        'MC_DRAWDOWN_AS_NEGATIVE': MC_DRAWDOWN_AS_NEGATIVE,
        'MC_PERCENTILES': MC_PERCENTILES,
        'MARKDOWN_IMAGE_SUBDIR': MARKDOWN_IMAGE_SUBDIR,
        'MARKDOWN_PLOT_FORMAT': MARKDOWN_PLOT_FORMAT,
        'LINES_PER_TEXT_PAGE': LINES_PER_TEXT_PAGE,
        'A4_LANDSCAPE': A4_LANDSCAPE,
        'MAX_XTICKS_BEFORE_RESIZE': MAX_XTICKS_BEFORE_RESIZE,
        'VERBOSE_DEBUG': VERBOSE_DEBUG,
        'CRITICAL_COLS': CRITICAL_COLS,
        'NUMERIC_COLS': NUMERIC_COLS,
        'WFA_SPLIT_RATIO': WFA_SPLIT_RATIO,
    }

    if args.all:
        # --- Batch mode ---
        run_dir = Path(args.all)
        analyzer_csvs_dir = run_dir / "analyzer_csvs"
        if not analyzer_csvs_dir.is_dir():
            print(f"ERROR: analyzer_csvs/ not found under: {args.all}")
            sys.exit(1)

        csv_files = sorted(analyzer_csvs_dir.rglob("*.csv"))
        if not csv_files:
            print(f"ERROR: No CSV files found under: {analyzer_csvs_dir}")
            sys.exit(1)

        # Load WFA split ratio from this run's config_snapshot.json (if present)
        wfa_ratio = _load_wfa_split_ratio(run_dir)
        if wfa_ratio is not None:
            print(f"WFA split ratio loaded from config_snapshot.json: {wfa_ratio}")

        output_dir = str(run_dir / "detailed_reports")
        _noise_csv = run_dir / "noise_sample_data.csv"
        config_params = {
            **base_config,
            'BASE_OUTPUT_DIRECTORY': output_dir,
            'WFA_SPLIT_RATIO': wfa_ratio,
            'NOISE_CSV_PATH': str(_noise_csv) if _noise_csv.is_file() else None,
        }
        count = 0
        for csv_file in csv_files:
            report_name = csv_file.stem
            print(f"Processing: {csv_file}")
            trades_df = pd.read_csv(csv_file)
            portfolio_timeline = _load_equity_file(csv_file.parent / f"{csv_file.stem}_equity.csv")
            this_config = {**config_params}
            if portfolio_timeline is not None:
                this_config['PORTFOLIO_TIMELINE'] = portfolio_timeline
            generate_trade_report(trades_df, output_dir, report_name, this_config)
            count += 1

        print(f"Generated {count} reports in {output_dir}")

    else:
        # --- Single-file mode ---
        csv_path = args.csv_path
        if not os.path.isfile(csv_path):
            print(f"ERROR: File not found: {csv_path}")
            sys.exit(1)

        # Dynamically determine output directory based on the CSV path.
        # If the CSV lives inside a run's analyzer_csvs/ folder, route the report
        # to detailed_reports/ inside the same run directory.
        if args.output_dir is not None:
            output_dir = args.output_dir
        else:
            csv_parts = Path(csv_path).parts
            if "analyzer_csvs" in csv_parts:
                idx = csv_parts.index("analyzer_csvs")
                base_run_dir = Path(*csv_parts[:idx])
                output_dir = str(base_run_dir / "detailed_reports")
            else:
                output_dir = "detailed_reports"

        # Load WFA split ratio from config_snapshot.json if the CSV is inside a run dir
        wfa_ratio = None
        csv_parts = Path(csv_path).parts
        if "analyzer_csvs" in csv_parts:
            idx = csv_parts.index("analyzer_csvs")
            wfa_ratio = _load_wfa_split_ratio(Path(*csv_parts[:idx]))
            if wfa_ratio is not None:
                print(f"WFA split ratio loaded from config_snapshot.json: {wfa_ratio}")

        if args.report_name:
            report_name = args.report_name
        else:
            report_name = os.path.splitext(os.path.basename(csv_path))[0]

        print(f"Loading trades from: {csv_path}")
        trades_df = pd.read_csv(csv_path)
        print(f"Loaded {len(trades_df)} trades.")

        _noise_csv_single = None
        csv_parts_check = Path(csv_path).parts
        if "analyzer_csvs" in csv_parts_check:
            idx_check = csv_parts_check.index("analyzer_csvs")
            _candidate = Path(*csv_parts_check[:idx_check]) / "noise_sample_data.csv"
            if _candidate.is_file():
                _noise_csv_single = str(_candidate)
        portfolio_timeline = _load_equity_file(Path(csv_path).parent / f"{report_name}_equity.csv")
        config_params = {
            **base_config,
            'BASE_OUTPUT_DIRECTORY': output_dir,
            'WFA_SPLIT_RATIO': wfa_ratio,
            'NOISE_CSV_PATH': _noise_csv_single,
        }
        if portfolio_timeline is not None:
            config_params['PORTFOLIO_TIMELINE'] = portfolio_timeline
        generate_trade_report(trades_df, output_dir, report_name, config_params)


if __name__ == "__main__":
    main()
