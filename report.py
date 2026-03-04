"""
Command-line script to generate detailed PDF/Markdown reports from backtester CSVs.

Usage:
    python report.py path/to/strategy.csv
    python report.py output/runs/2026-03-02_14-00-00/analyzer_csvs/Nasdaq_100/EMA_Regime.csv
"""
import argparse
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
)
from trade_analyzer.analyzer import generate_trade_report


def main():
    parser = argparse.ArgumentParser(
        description="Generate a detailed PDF/Markdown trade analysis report from a CSV file."
    )
    parser.add_argument(
        "csv_path",
        help="Path to a backtester-generated CSV file (with analyzer-compatible columns).",
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

    if args.report_name:
        report_name = args.report_name
    else:
        report_name = os.path.splitext(os.path.basename(csv_path))[0]

    print(f"Loading trades from: {csv_path}")
    trades_df = pd.read_csv(csv_path)
    print(f"Loaded {len(trades_df)} trades.")

    config_params = {
        'BASE_OUTPUT_DIRECTORY': output_dir,
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
    }

    generate_trade_report(trades_df, output_dir, report_name, config_params)


if __name__ == "__main__":
    main()
