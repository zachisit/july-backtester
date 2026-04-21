"""helpers/cli_config.py — CLI config override system for july-backtester.

Public API:
  build_parser()                      -> argparse.ArgumentParser
  apply_overrides(config_dict, args)  -> dict  (mutates + returns)
  parse_stop_token(token)             -> dict
  cast_value(s)                       -> int | float | bool | str
  print_help_config(config_dict, category)
"""
from __future__ import annotations

import argparse
import sys
from typing import Any

from version import __version__


# ---------------------------------------------------------------------------
# Stop token parser
# ---------------------------------------------------------------------------

def parse_stop_token(token: str) -> dict:
    """Parse a stop-loss shorthand token into a config dict.

    Supported formats:
      none           -> {"type": "none"}
      pct:0.05       -> {"type": "percentage", "value": 0.05}
      atr:14:3.0     -> {"type": "atr", "period": 14, "multiplier": 3.0}
    """
    t = token.strip().lower()
    if t == "none":
        return {"type": "none"}
    if t.startswith("pct:"):
        parts = t.split(":")
        if len(parts) != 2:
            raise ValueError(
                f"Invalid pct stop token: {token!r}. Expected pct:<value>, e.g. pct:0.05"
            )
        return {"type": "percentage", "value": float(parts[1])}
    if t.startswith("atr:"):
        parts = t.split(":")
        if len(parts) != 3:
            raise ValueError(
                f"Invalid atr stop token: {token!r}. "
                "Expected atr:<period>:<multiplier>, e.g. atr:14:3.0"
            )
        return {"type": "atr", "period": int(parts[1]), "multiplier": float(parts[2])}
    raise ValueError(
        f"Unknown stop token: {token!r}. "
        "Use: none | pct:<value> | atr:<period>:<multiplier>"
    )


# ---------------------------------------------------------------------------
# Value caster for --set
# ---------------------------------------------------------------------------

def cast_value(s: str) -> Any:
    """Auto-cast a string to int, float, bool, or str (in that order)."""
    if s.lower() == "true":
        return True
    if s.lower() == "false":
        return False
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s


# ---------------------------------------------------------------------------
# Parser builder
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    """Return the full ArgumentParser for main.py."""
    parser = argparse.ArgumentParser(
        description="Portfolio Backtester",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Run 'python main.py --help-config' for a guided tour of all settings.\n"
            "Run 'python main.py --help-config <category>' for a specific section.\n"
            "Categories: data, period, portfolio, strategies, costs, stop, "
            "filtering, mc, wfa, output\n"
        ),
    )

    parser.add_argument(
        "--version", action="version",
        version=f"july-backtester {__version__}",
    )

    # ---- Existing flags (unchanged behaviour) ----
    parser.add_argument(
        "--name", type=str,
        help="Optional prefix for the report folder name.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Validate config and print summary without fetching data or running simulations.",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Show all columns in the summary table (default: compact view).",
    )
    parser.add_argument("--init", action="store_true", help=argparse.SUPPRESS)

    # ---- Guided help ----
    parser.add_argument(
        "--help-config", nargs="?", const="all", metavar="CATEGORY",
        help=(
            "Print the config reference guide. Optionally filter by category: "
            "data, period, portfolio, strategies, costs, stop, filtering, mc, wfa, output"
        ),
    )

    # ---- DATA ----
    parser.add_argument(
        "--provider", dest="data_provider", metavar="PROVIDER",
        help="Data source: norgate | yahoo | polygon | csv | parquet",
    )
    parser.add_argument(
        "--csv-dir", dest="csv_data_dir", metavar="PATH",
        help="Folder of per-symbol CSV files (--provider csv only)",
    )
    parser.add_argument(
        "--parquet-dir", dest="parquet_data_dir", metavar="PATH",
        help="Folder of per-symbol Parquet files (--provider parquet only)",
    )

    # ---- PERIOD & CAPITAL ----
    parser.add_argument(
        "--start", dest="start_date", metavar="YYYY-MM-DD",
        help="Backtest start date",
    )
    parser.add_argument(
        "--end", dest="end_date", metavar="YYYY-MM-DD",
        help="Backtest end date",
    )
    parser.add_argument(
        "--capital", dest="initial_capital", type=float, metavar="USD",
        help="Starting equity in USD",
    )

    # ---- PORTFOLIO & SYMBOLS (mutually exclusive) ----
    sym_group = parser.add_mutually_exclusive_group()
    sym_group.add_argument(
        "--symbols", nargs="+", metavar="TICKER",
        help="One or more tickers to run as a 'CLI' portfolio",
    )
    sym_group.add_argument(
        "--portfolio", metavar="FILE_OR_WATCHLIST",
        help="JSON filename or norgate:WatchlistName as a 'CLI' portfolio",
    )
    parser.add_argument(
        "--min-bars", dest="min_bars_required", type=int, metavar="N",
        help="Skip symbols with fewer than N bars",
    )

    # ---- STRATEGIES ----
    parser.add_argument(
        "--strategies", nargs="+", metavar="NAME",
        help="Exact strategy names to run; use 'all' to run every registered strategy",
    )

    # ---- EXECUTION & COSTS ----
    parser.add_argument(
        "--allocation", dest="allocation_per_trade", type=float, metavar="FRAC",
        help="Fraction of equity per position, e.g. 0.05",
    )
    parser.add_argument(
        "--execution", dest="execution_time", metavar="TIME",
        help="Fill time: open | close",
    )
    parser.add_argument(
        "--slippage", dest="slippage_pct", type=float, metavar="FRAC",
        help="Flat bid/ask slippage fraction, e.g. 0.0005",
    )
    parser.add_argument(
        "--commission", dest="commission_per_share", type=float, metavar="USD",
        help="Commission per share in USD, e.g. 0.002",
    )
    parser.add_argument(
        "--risk-free-rate", dest="risk_free_rate", type=float, metavar="RATE",
        help="Annual risk-free rate for Sharpe/Sortino, e.g. 0.05",
    )
    parser.add_argument(
        "--htb-rate", dest="htb_rate_annual", type=float, metavar="RATE",
        help="Annual hard-to-borrow rate for short positions, e.g. 0.02",
    )
    parser.add_argument(
        "--max-pct-adv", dest="max_pct_adv", type=float, metavar="FRAC",
        help="Max fraction of 20-day ADV per order, e.g. 0.05",
    )
    parser.add_argument(
        "--volume-impact", dest="volume_impact_coeff", type=float, metavar="COEFF",
        help="Square-root market impact coefficient. 0.0 = disabled",
    )

    # ---- STOP LOSS ----
    parser.add_argument(
        "--stop", dest="stop_tokens", nargs="+", metavar="TOKEN",
        help="Stop configs: none | pct:0.05 | atr:14:3.0 (repeatable)",
    )

    # ---- FILTERING ----
    parser.add_argument(
        "--min-pandl", dest="min_pandl_to_show_in_summary", type=float, metavar="PCT",
        help="Min P&L %% to show in summary. -9999 = show all",
    )
    parser.add_argument(
        "--max-dd", dest="max_acceptable_drawdown", type=float, metavar="FRAC",
        help="Max drawdown to display, e.g. 0.25. 1.0 = show all",
    )
    parser.add_argument(
        "--min-mc-score", dest="mc_score_min_to_show_in_summary", type=float, metavar="SCORE",
        help="Min MC score to display. -9999 = show all",
    )
    parser.add_argument(
        "--min-vs-spy", dest="min_performance_vs_spy", type=float, metavar="PCT",
        help="Min outperformance vs SPY. 0.0 = must beat. -9999 = show all",
    )

    # ---- MONTE CARLO ----
    parser.add_argument(
        "--mc-sims", dest="num_mc_simulations", type=int, metavar="N",
        help="Number of MC simulations",
    )
    parser.add_argument(
        "--min-trades-mc", dest="min_trades_for_mc", type=int, metavar="N",
        help="Min trades required to run MC",
    )
    parser.add_argument(
        "--mc-sampling", dest="mc_sampling", metavar="METHOD",
        help="MC resampling method: iid | block",
    )

    # ---- WFA ----
    parser.add_argument(
        "--wfa-split", dest="wfa_split_ratio", type=float, metavar="RATIO",
        help="WFA in-sample fraction, e.g. 0.80. 0 = disable WFA",
    )
    parser.add_argument(
        "--wfa-folds", dest="wfa_folds", type=int, metavar="N",
        help="Rolling WFA folds. 0 = disable rolling WFA",
    )

    # ---- OUTPUT & MISC ----
    parser.add_argument(
        "--save-trades", dest="save_individual_trades",
        action=argparse.BooleanOptionalAction,
        help="Save per-strategy trade CSVs (default: on)",
    )
    parser.add_argument(
        "--save-filtered-only", dest="save_only_filtered_trades",
        action=argparse.BooleanOptionalAction,
        help="Only save trades for strategies that passed display filters",
    )
    parser.add_argument(
        "--noise", dest="noise_injection_pct", type=float, metavar="FRAC",
        help="Price noise injection fraction. 0.0 = disabled",
    )
    parser.add_argument(
        "--rolling-sharpe", dest="rolling_sharpe_window", type=int, metavar="BARS",
        help="Rolling Sharpe window in trading days. 0 = disabled",
    )
    parser.add_argument(
        "--export-ml", dest="export_ml_features",
        action=argparse.BooleanOptionalAction,
        help="Export ML trade features to Parquet after the run",
    )
    parser.add_argument(
        "--upload-s3", dest="upload_to_s3",
        action=argparse.BooleanOptionalAction,
        help="Upload reports to the configured S3 bucket",
    )

    # ---- ESCAPE HATCH ----
    parser.add_argument(
        "--set", dest="overrides", action="append", metavar="KEY=VALUE",
        help=(
            "Override any config key not covered by a named flag, "
            "e.g. --set rolling_sharpe_window=252. Repeatable."
        ),
    )

    return parser


# ---------------------------------------------------------------------------
# Apply overrides
# ---------------------------------------------------------------------------

# Keys with a direct 1-to-1 mapping between argparse dest and CONFIG key.
_DIRECT_KEYS = [
    "data_provider", "csv_data_dir", "parquet_data_dir",
    "start_date", "end_date", "initial_capital",
    "min_bars_required",
    "allocation_per_trade", "execution_time",
    "slippage_pct", "commission_per_share", "risk_free_rate",
    "htb_rate_annual", "max_pct_adv", "volume_impact_coeff",
    "min_pandl_to_show_in_summary", "max_acceptable_drawdown",
    "mc_score_min_to_show_in_summary", "min_performance_vs_spy",
    "num_mc_simulations", "min_trades_for_mc", "mc_sampling",
    "save_individual_trades", "save_only_filtered_trades",
    "noise_injection_pct", "rolling_sharpe_window",
    "export_ml_features", "upload_to_s3",
]


def apply_overrides(config_dict: dict, args: argparse.Namespace) -> dict:
    """Apply parsed CLI args to config_dict in-place. Returns config_dict."""

    # 1. Direct 1:1 keys — only apply when explicitly set (not None)
    for key in _DIRECT_KEYS:
        val = getattr(args, key, None)
        if val is not None:
            config_dict[key] = val

    # 2. portfolios: --symbols builds an inline list; --portfolio builds a file/watchlist ref
    if getattr(args, "symbols", None):
        config_dict["portfolios"] = {"CLI": list(args.symbols)}
    elif getattr(args, "portfolio", None):
        config_dict["portfolios"] = {"CLI": args.portfolio}

    # 3. strategies: 'all' string or list of names
    if getattr(args, "strategies", None):
        strats = args.strategies
        if len(strats) == 1 and strats[0].lower() == "all":
            config_dict["strategies"] = "all"
        else:
            config_dict["strategies"] = list(strats)

    # 4. stop_loss_configs from shorthand tokens
    if getattr(args, "stop_tokens", None):
        config_dict["stop_loss_configs"] = [
            parse_stop_token(t) for t in args.stop_tokens
        ]

    # 5. wfa_split_ratio: 0.0 means disabled (None)
    wfa_split = getattr(args, "wfa_split_ratio", None)
    if wfa_split is not None:
        config_dict["wfa_split_ratio"] = None if wfa_split == 0.0 else wfa_split

    # 6. wfa_folds: 0 means disabled (None)
    wfa_folds = getattr(args, "wfa_folds", None)
    if wfa_folds is not None:
        config_dict["wfa_folds"] = None if wfa_folds == 0 else wfa_folds

    # 7. --set escape hatch
    for item in (getattr(args, "overrides", None) or []):
        if "=" not in item:
            print(f"[WARNING] --set value ignored (no '='): {item!r}", file=sys.stderr)
            continue
        k, v = item.split("=", 1)
        config_dict[k.strip()] = cast_value(v.strip())

    return config_dict


# ---------------------------------------------------------------------------
# Guided help
# ---------------------------------------------------------------------------

_SECTIONS: list[tuple[str, str, list[dict]]] = [
    ("data", "DATA", [
        {
            "flag": "--provider <str>",
            "config_key": "data_provider",
            "desc": "Which data source to use.",
            "options": "norgate | yahoo | polygon | csv | parquet",
            "example": "python main.py --provider yahoo",
        },
        {
            "flag": "--csv-dir <path>",
            "config_key": "csv_data_dir",
            "desc": "Folder of per-symbol CSV files (--provider csv only).",
            "options": None,
            "example": "python main.py --provider csv --csv-dir ./my_data",
        },
        {
            "flag": "--parquet-dir <path>",
            "config_key": "parquet_data_dir",
            "desc": "Folder of per-symbol Parquet files (--provider parquet only).",
            "options": None,
            "example": "python main.py --provider parquet --parquet-dir ./parquet_data",
        },
    ]),
    ("period", "PERIOD & CAPITAL", [
        {
            "flag": "--start <YYYY-MM-DD>",
            "config_key": "start_date",
            "desc": "Backtest start date.",
            "options": None,
            "example": "python main.py --start 2015-01-01",
        },
        {
            "flag": "--end <YYYY-MM-DD>",
            "config_key": "end_date",
            "desc": "Backtest end date. Defaults to today.",
            "options": None,
            "example": "python main.py --end 2023-12-31",
        },
        {
            "flag": "--capital <float>",
            "config_key": "initial_capital",
            "desc": "Starting equity in USD.",
            "options": None,
            "example": "python main.py --capital 50000",
        },
    ]),
    ("portfolio", "PORTFOLIO & SYMBOLS", [
        {
            "flag": "--symbols <TICKER> [<TICKER> ...]",
            "config_key": "portfolios",
            "desc": (
                "One or more tickers as an inline 'CLI' portfolio.\n"
                "      Mutually exclusive with --portfolio."
            ),
            "options": None,
            "example": "python main.py --symbols AAPL MSFT NVDA",
        },
        {
            "flag": "--portfolio <FILE_OR_WATCHLIST>",
            "config_key": "portfolios",
            "desc": (
                "JSON file or Norgate watchlist name as a 'CLI' portfolio.\n"
                "      Mutually exclusive with --symbols."
            ),
            "options": None,
            "example": "python main.py --portfolio nasdaq_100.json",
        },
        {
            "flag": "--min-bars <int>",
            "config_key": "min_bars_required",
            "desc": "Skip any symbol with fewer bars than this.",
            "options": None,
            "example": "python main.py --min-bars 500",
        },
    ]),
    ("strategies", "STRATEGIES", [
        {
            "flag": "--strategies <NAME> [<NAME> ...]",
            "config_key": "strategies",
            "desc": (
                "Exact strategy names to run (case-sensitive).\n"
                "      Use 'all' to run every registered strategy."
            ),
            "options": None,
            "example": 'python main.py --strategies "SMA Crossover (20d/50d)"',
        },
    ]),
    ("costs", "EXECUTION & COSTS", [
        {
            "flag": "--allocation <float>",
            "config_key": "allocation_per_trade",
            "desc": "Fraction of total equity allocated per position (0.10 = 10%).",
            "options": "0 < value <= 1.0",
            "example": "python main.py --allocation 0.05",
        },
        {
            "flag": "--execution <str>",
            "config_key": "execution_time",
            "desc": "Fill time for entries and exits.",
            "options": "open | close",
            "example": "python main.py --execution close",
        },
        {
            "flag": "--slippage <float>",
            "config_key": "slippage_pct",
            "desc": "Flat bid/ask slippage fraction on every fill.",
            "options": None,
            "example": "python main.py --slippage 0.001",
        },
        {
            "flag": "--commission <float>",
            "config_key": "commission_per_share",
            "desc": "Commission in USD per share.",
            "options": None,
            "example": "python main.py --commission 0.005",
        },
        {
            "flag": "--risk-free-rate <float>",
            "config_key": "risk_free_rate",
            "desc": "Annual risk-free rate used in Sharpe/Sortino ratio.",
            "options": None,
            "example": "python main.py --risk-free-rate 0.04",
        },
        {
            "flag": "--htb-rate <float>",
            "config_key": "htb_rate_annual",
            "desc": "Annual hard-to-borrow rate debited daily on open short positions.",
            "options": None,
            "example": "python main.py --htb-rate 0.10",
        },
        {
            "flag": "--max-pct-adv <float>",
            "config_key": "max_pct_adv",
            "desc": "Max fraction of 20-day ADV a single order may consume.",
            "options": None,
            "example": "python main.py --max-pct-adv 0.10",
        },
        {
            "flag": "--volume-impact <float>",
            "config_key": "volume_impact_coeff",
            "desc": "Square-root market impact coefficient. 0.0 = disabled.",
            "options": None,
            "example": "python main.py --volume-impact 0.1",
        },
    ]),
    ("stop", "STOP LOSS", [
        {
            "flag": "--stop <TOKEN> [<TOKEN> ...]",
            "config_key": "stop_loss_configs",
            "desc": (
                "One or more stop configs using shorthand tokens:\n"
                "      none          no stop loss\n"
                "      pct:0.05      5% percentage stop\n"
                "      atr:14:3.0    ATR stop (period=14, multiplier=3.0)"
            ),
            "options": "none | pct:<value> | atr:<period>:<multiplier>",
            "example": "python main.py --stop pct:0.05 pct:0.10 atr:14:3.0",
        },
    ]),
    ("filtering", "FILTERING", [
        {
            "flag": "--min-pandl <float>",
            "config_key": "min_pandl_to_show_in_summary",
            "desc": "Only display strategies with P&L >= this value. -9999 = show all.",
            "options": None,
            "example": "python main.py --min-pandl 10.0",
        },
        {
            "flag": "--max-dd <float>",
            "config_key": "max_acceptable_drawdown",
            "desc": "Only display strategies with max drawdown <= this fraction. 1.0 = show all.",
            "options": None,
            "example": "python main.py --max-dd 0.25",
        },
        {
            "flag": "--min-mc-score <float>",
            "config_key": "mc_score_min_to_show_in_summary",
            "desc": "Only display strategies with MC score >= this value. -9999 = show all.",
            "options": None,
            "example": "python main.py --min-mc-score 50",
        },
        {
            "flag": "--min-vs-spy <float>",
            "config_key": "min_performance_vs_spy",
            "desc": "Only display strategies that outperformed SPY by at least this %. -9999 = show all.",
            "options": None,
            "example": "python main.py --min-vs-spy 0.0",
        },
    ]),
    ("mc", "MONTE CARLO", [
        {
            "flag": "--mc-sims <int>",
            "config_key": "num_mc_simulations",
            "desc": "Number of Monte Carlo simulation runs.",
            "options": None,
            "example": "python main.py --mc-sims 2000",
        },
        {
            "flag": "--min-trades-mc <int>",
            "config_key": "min_trades_for_mc",
            "desc": "Minimum trades required before running MC (fewer = skip MC).",
            "options": None,
            "example": "python main.py --min-trades-mc 30",
        },
        {
            "flag": "--mc-sampling <str>",
            "config_key": "mc_sampling",
            "desc": "Resampling method. iid = independent. block = preserves streaks/regimes.",
            "options": "iid | block",
            "example": "python main.py --mc-sampling block",
        },
    ]),
    ("wfa", "WALK-FORWARD ANALYSIS", [
        {
            "flag": "--wfa-split <float>",
            "config_key": "wfa_split_ratio",
            "desc": "Fraction of data used as in-sample period. 0 = disable WFA.",
            "options": "0 (disable) | 0.60 - 0.90",
            "example": "python main.py --wfa-split 0.70",
        },
        {
            "flag": "--wfa-folds <int>",
            "config_key": "wfa_folds",
            "desc": "Number of rolling WFA folds. 0 = disable rolling WFA.",
            "options": "0 (disable) | int >= 2",
            "example": "python main.py --wfa-folds 5",
        },
    ]),
    ("output", "OUTPUT & MISC", [
        {
            "flag": "--save-trades / --no-save-trades",
            "config_key": "save_individual_trades",
            "desc": "Save per-strategy trade CSVs to the run folder.",
            "options": None,
            "example": "python main.py --no-save-trades",
        },
        {
            "flag": "--save-filtered-only / --no-save-filtered-only",
            "config_key": "save_only_filtered_trades",
            "desc": "Only save trades for strategies that passed display filters.",
            "options": None,
            "example": "python main.py --save-filtered-only",
        },
        {
            "flag": "--noise <float>",
            "config_key": "noise_injection_pct",
            "desc": "Inject random OHLC noise to stress-test robustness. 0.0 = disabled.",
            "options": None,
            "example": "python main.py --noise 0.01",
        },
        {
            "flag": "--rolling-sharpe <int>",
            "config_key": "rolling_sharpe_window",
            "desc": "Rolling Sharpe window in trading days. 0 = disabled.",
            "options": None,
            "example": "python main.py --rolling-sharpe 63",
        },
        {
            "flag": "--export-ml / --no-export-ml",
            "config_key": "export_ml_features",
            "desc": "Write consolidated ml_features.parquet after the run.",
            "options": None,
            "example": "python main.py --export-ml",
        },
        {
            "flag": "--upload-s3 / --no-upload-s3",
            "config_key": "upload_to_s3",
            "desc": "Upload report files to the configured S3 bucket.",
            "options": None,
            "example": "python main.py --upload-s3",
        },
        {
            "flag": "--set <KEY>=<VALUE>",
            "config_key": "(any)",
            "desc": (
                "Override any config key not covered by a named flag.\n"
                "      Value is auto-cast: int, float, true/false, or string.\n"
                "      Repeatable."
            ),
            "options": None,
            "example": "python main.py --set rolling_sharpe_window=252 --set htb_rate_annual=0.15",
        },
    ]),
]

VALID_CATEGORIES: list[str] = [s[0] for s in _SECTIONS]


def print_help_config(config_dict: dict, category: str | None = None) -> None:
    """Print the guided config reference to stdout."""
    W = 66

    if category is not None and category.lower() not in ("all", ""):
        cat = category.lower()
        if cat not in VALID_CATEGORIES:
            print(f"\nUnknown category: {cat!r}")
            print(f"Valid categories: {', '.join(VALID_CATEGORIES)}\n")
            return
        sections = [s for s in _SECTIONS if s[0] == cat]
    else:
        sections = _SECTIONS

    print()
    print("+" + "=" * W + "+")
    print("|" + "  july-backtester  --  Config Reference  ".center(W) + "|")
    print("+" + "=" * W + "+")

    for _key, title, entries in sections:
        print()
        dash_count = max(W - len(title) - 4, 4)
        print(f"  {title}  " + "-" * dash_count)

        for entry in entries:
            print()
            print(f"  {entry['flag']}")
            for line in entry["desc"].splitlines():
                print(f"      {line}")
            # Current live value from config
            ckey = entry["config_key"]
            if ckey != "(any)" and ckey in config_dict:
                raw = config_dict[ckey]
                if ckey == "portfolios":
                    display = "(see config.py)"
                elif ckey == "initial_capital":
                    display = f"{raw:,.0f}"
                elif isinstance(raw, float) and raw == int(raw):
                    display = str(int(raw))
                else:
                    display = str(raw)
                print(f"      Current : {display}")
            if entry.get("options"):
                print(f"      Options : {entry['options']}")
            print(f"      Example : {entry['example']}")

    print()
    print("  Quick-start examples:")
    print("    python main.py --provider yahoo --symbols AAPL --start 2020-01-01 --capital 25000")
    print("    python main.py --portfolio nasdaq_100.json --min-vs-spy 0.0")
    print("    python main.py --stop pct:0.05 atr:14:3.0 --mc-sims 2000 --min-pandl 5.0")
    print("    python main.py --set rolling_sharpe_window=252 --set htb_rate_annual=0.15")
    print()
    if category is None or category.lower() in ("all", ""):
        print(f"  Filter by category: python main.py --help-config <category>")
        print(f"  Valid categories  : {', '.join(VALID_CATEGORIES)}")
    print()
