# July Backtester

A systematic strategy backtesting engine for US equities. Test 20+ built-in technical strategies across individual symbols or large portfolios (Nasdaq, S&P 500, Russell indices, etc.), with Monte Carlo simulation for robustness scoring, benchmark comparison against SPY and QQQ, and automatic report generation.

---

## Table of Contents

1. [What This Tool Does](#what-this-tool-does)
2. [Prerequisites](#prerequisites)
3. [Installation](#installation)
4. [API Key Setup](#api-key-setup)
5. [Configuration](#configuration)
6. [Running the Backtester](#running-the-backtester)
7. [Understanding the Output](#understanding-the-output)
8. [Generating Detailed Reports](#generating-detailed-reports)
9. [Available Strategies](#available-strategies)
10. [Configuration Reference](#configuration-reference)
11. [Data Caching](#data-caching)
12. [Adding Custom Strategies](#adding-custom-strategies)
13. [Project Structure](#project-structure)
14. [Contributing](#contributing)

---

## What This Tool Does

The backtester takes a strategy that you create (e.g., "buy when the 20-day SMA crosses above the 50-day SMA"), simulates it against historical price data for one or many stocks, and produces a performance report. You can run a single strategy or sweep many strategies simultaneously to find what works.

**Two modes:**

- **Single-Asset Mode** — Tests all strategies against one or a small list of specific tickers (e.g., just AAPL or BITB). Good for deep-diving a specific stock. Set `symbols_to_test` in `config.py` and run `python main.py`.
- **Portfolio Mode** — Tests strategies against an entire index or portfolio (e.g., every stock in the Nasdaq 100). Runs in parallel across all your CPU cores. This is the primary research tool. Set `portfolios` in `config.py` and run `python main.py`.

Both modes are accessed through the single entry point `main.py`. Portfolio mode is the default.

**What you get out:**

- Total P&L %, Max Drawdown, Sharpe Ratio, Calmar Ratio, Win Rate, Profit Factor
- Performance vs SPY Buy & Hold and QQQ Buy & Hold
- Monte Carlo robustness score (1,000 simulations per strategy to test if results are due to luck)
- Per-run output folder with logs, trade CSVs, and analyzer-ready files
- Optional: detailed PDF/Markdown reports via `report.py`, S3 uploads

---

## Prerequisites

Before starting, you will need:

1. **Python 3.10 or higher** — [Download here](https://www.python.org/downloads/)
2. **A Polygon.io account** — [Sign up here](https://polygon.io/). A paid plan is required for full historical data (the free tier is limited to 2 years of daily data). The Stocks Starter plan (~$29/month) covers most use cases.

**For Norgate users:** If you have a [Norgate Data](https://norgatedata.com/) subscription and the Norgate Data Updater installed locally, you can use Norgate as the data provider instead of Polygon. See [Data Provider Settings](#data-provider-settings) below.

---

## Installation

### Step 1 — Clone the Repository

```bash
git clone <repository-url>
cd july-backtester
```

### Step 2 — Create a Python Virtual Environment

A virtual environment keeps this project's dependencies isolated from your system Python. This is strongly recommended.

```bash
# Create the virtual environment
python -m venv venv

# Activate it — macOS / Linux
source venv/bin/activate

# Activate it — Windows (Command Prompt)
venv\Scripts\activate.bat

# Activate it — Windows (PowerShell)
venv\Scripts\Activate.ps1
```

You should see `(venv)` appear at the start of your terminal prompt. Every time you open a new terminal to use this tool, you need to activate the virtual environment again before running any commands.

### Step 3 — Install Dependencies

```bash
pip install -r requirements.txt
```

This installs: `pandas`, `numpy`, `tqdm`, `boto3` (S3 uploads only), `requests`, `python-dotenv`, `pandas-ta`, `orjson`, `pyarrow`.

---

## API Key Setup

The backtester reads your Polygon.io API key directly from a `.env` file or environment variable — no AWS configuration required.

1. Get your Polygon.io API key from [https://polygon.io/dashboard/api-keys](https://polygon.io/dashboard/api-keys)

2. Copy `.env.example` to `.env` in the project root:

   ```bash
   cp .env.example .env
   ```

3. Open `.env` and add your key:

   ```env
   POLYGON_API_KEY=your_key_here
   ```

4. That's it. The backtester reads `POLYGON_API_KEY` at runtime. No changes to `config.py` are needed for the default setup.

Your `.env` file is gitignored and will never be committed. If you prefer not to use a `.env` file, you can also set `POLYGON_API_KEY` as a standard system environment variable and the tool will pick it up automatically.

### (Optional) Set Up an S3 Bucket for Reports

If you want reports automatically uploaded to S3 after each run:

1. Create an S3 bucket in the AWS Console (e.g., `my-backtester-reports`) and make note of its name.
2. Ensure your environment has AWS credentials configured (via `~/.aws/credentials` or environment variables `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`).
3. Update `config.py`:

```python
"upload_to_s3": True,
"s3_reports_bucket": "my-backtester-reports",
```

S3 uploads are entirely optional. If `upload_to_s3` is `False` or `s3_reports_bucket` is empty, all output is saved locally and no AWS connection is attempted. `boto3` is only used for this S3 upload step — it is not involved in API key management.

---

## Configuration

All settings live in one file: [config.py](config.py). Open it in any text editor before running. The file is organized into labeled sections with comments explaining each setting.

### Quick Setup Checklist

- [ ] Add `POLYGON_API_KEY` to your `.env` file (copy `.env.example` to get started)
- [ ] Set `upload_to_s3` and `s3_reports_bucket` if you want S3 uploads (optional)
- [ ] Choose `data_provider`: `"polygon"` or `"norgate"`
- [ ] Set `start_date` and `initial_capital`
- [ ] For portfolio mode: uncomment the portfolios you want in the `portfolios` dict
- [ ] For single-asset mode: set `symbols_to_test`

### Data Provider Settings

```python
"data_provider": "polygon",   # Polygon.io — API key via .env or environment variable
# "data_provider": "norgate", # Norgate Data — requires local Norgate installation
```

### Backtest Period

```python
"start_date": "2004-01-01",                            # How far back to test
"end_date": datetime.now().strftime('%Y-%m-%d'),        # Defaults to today
```

Setting `start_date` to a date earlier than the provider's available data is fine — the tool will use whatever the earliest available bar is.

### Capital and Position Sizing

```python
"initial_capital": 100000.0,   # Simulated account size in dollars
"allocation_per_trade": 0.10,  # 10% of equity per new position (allows up to 10 concurrent)
```

### What to Test

**Single-Asset Mode:**

```python
"symbols_to_test": ['AAPL'],                      # One ticker
"symbols_to_test": ['AAPL', 'TSLA', 'NVDA'],      # Several tickers
```

**Portfolio Mode** — edit the `portfolios` dictionary in `config.py`. Comment out entries you do not want to run:

```python
"portfolios": {
    "Nasdaq 100": "nasdaq_100.json",                      # Pre-built index list (~100 symbols)
    # "Nasdaq": "nasdaq.json",                            # Full Nasdaq (~3,000 symbols — slow)
    # "SP 500": "sp-500.json",                            # S&P 500
    "My Watchlist": ["AAPL", "MSFT", "GOOGL", "AMZN"],   # A manual list
},
```

> **Start small.** Running the full Nasdaq can take 30–60 minutes on the first run (data fetching). Use `"Nasdaq 100"` to validate your setup first.

**Norgate Watchlists:** If you use Norgate as your data provider, you can reference watchlists by name directly without creating a JSON file:

```python
"portfolios": {
    "Nasdaq Biotechnology": "norgate:Nasdaq Biotechnology",
},
```

### Stop Loss Configuration

```python
"stop_loss_configs": [
    {"type": "none"},                                   # No stop — hold until signal reverses
    # {"type": "percentage", "value": 0.05},            # 5% fixed stop below entry
    # {"type": "atr", "period": 14, "multiplier": 3.0}, # 3x ATR trailing stop
],
```

Include multiple entries to test each strategy with each stop type in the same run. Be aware that each additional stop type multiplies the total number of simulations.

### Slippage and Commission

```python
"slippage_pct": 0.0005,          # 0.05% slippage per fill (5 basis points)
"commission_per_share": 0.002,   # $0.002 per share commission
```

### Output Filters

These control what appears in the printed summary table and which trade logs get saved. Setting any to `-9999` effectively disables that filter (shows everything).

```python
"mc_score_min_to_show_in_summary": 3,       # Only show strategies with MC score >= 3
"min_pandl_to_show_in_summary": 5.0,        # Only show strategies with P&L >= 5%
"max_acceptable_drawdown": 0.30,            # Only show strategies with max DD <= 30%
"min_performance_vs_spy": 0.0,              # Only show strategies that beat SPY buy-and-hold
"save_only_filtered_trades": False,         # If True, only saves trades for filtered strategies
```

---

## Running the Backtester

Make sure your virtual environment is activated (`source venv/bin/activate` or the Windows equivalent) before running.

### Portfolio Mode (Primary Use)

Tests all active strategies in `strategies.py` against all uncommented portfolios in `config.py`. Uses all CPU cores.

```bash
python main.py
```

With an optional run name (added as a prefix to the output folder):

```bash
python main.py --name "nasdaq-sma-sweep"
```

### Dry Run — Validate Without Fetching Data

Runs all startup checks (API key, config validation) and prints the run summary without fetching any market data or running simulations. Use this to confirm your configuration — portfolio sizes, strategy count, and total task estimate — before committing to a long run.

```bash
python main.py --dry-run

# Combine with --name to preview the run ID that will be used
python main.py --dry-run --name "my-next-run"
```

### Single-Asset Mode

Tests strategies against the symbols listed in `symbols_to_test` in `config.py`. Update that list first, then run the same entry point:

```bash
python main.py
```

> To use single-asset mode, set `symbols_to_test` in `config.py` and make sure the `portfolios` dict only contains the symbols you want (or wrap them as a portfolio entry like `"My Tickers": ["AAPL", "TSLA"]`).

### First Run Tips

1. **Validate with one symbol first.** Set `"portfolios": {"Test": ["SPY", "QQQ"]}` and confirm the run completes without errors before testing larger lists.
2. **Watch for API key errors.** If you see `Could not find 'POLYGON_API_KEY'` in the terminal, your `.env` file is missing or the variable name doesn't match.
3. **The first run is the slowest.** Data is fetched from Polygon and cached locally. Subsequent runs within 24 hours load from disk and are much faster.

---

## Understanding the Output

### Run Output Folder

Every backtest creates a timestamped folder under `output/runs/`:

```text
output/
└── runs/
    └── <run_id>/                        # e.g. 2026-03-02_15-12-32 or myname_2026-03-02_15-12-32
        ├── logs/                        # Execution log: run_<timestamp>.log
        ├── raw_trades/                  # Per-portfolio raw trade CSVs (when save_individual_trades=True)
        │   └── <Portfolio_Name>/
        ├── analyzer_csvs/               # Renamed + column-mapped CSVs ready for report.py
        │   └── <Portfolio_Name>/
        ├── detailed_reports/            # PDFs / Markdown generated by report.py
        ├── config_snapshot.json         # Copy of config.py settings used for this run
        └── overall_portfolio_summary.csv
```

The entire `output/` directory is gitignored. Each run is isolated in its own folder — previous runs are never overwritten. S3 uploads (if configured) mirror this same `<run_id>/` structure as the key prefix.

### Terminal Summary Table

After each portfolio finishes, a results table is printed to the terminal:

```text
Strategy                      P&L (%)  vs. SPY  Max DD  Calmar  Sharpe  Win Rate  Trades  MC Verdict   MC Score
SMA Crossover (20d/50d)        +89.4%   +21.3%   41.5%    1.12    0.71     48.9%     287   Mod. Tail Risk     2
SMA Crossover (50d/200d)       +74.1%   +12.1%   38.2%    0.98    0.65     46.1%     214   Good               3
```

**Column definitions:**

| Column | Meaning |
| --- | --- |
| P&L (%) | Total return over the full backtest period |
| vs. SPY / vs. QQQ | Outperformance vs buy-and-hold of those indices |
| Max DD | Largest peak-to-trough decline during the period |
| Calmar | Annualized return divided by max drawdown (higher = better risk-adjusted return) |
| Sharpe | Risk-adjusted return relative to volatility (above 1.0 is generally considered good; above 2.0 is strong) |
| Win Rate | Percentage of trades that were profitable |
| Trades | Total number of completed trades |
| MC Verdict | Robustness classification from Monte Carlo analysis |
| MC Score | Numeric robustness score (see below) |

### Monte Carlo Score Explained

Every strategy with 50+ trades is stress-tested with 1,000 simulations that randomly reshuffle the historical trade sequence. This reveals whether results depend on lucky ordering or are genuinely robust.

| Score | Verdict | What It Means |
| --- | --- | --- |
| 5 | Robust | Consistent across simulations. Results are likely genuine. |
| 3–4 | Good | Solid with minor concerns. Worth investigating further. |
| 1–2 | Moderate | Some robustness concerns. Proceed with caution. |
| ≤ 0 | Weak / Perf. Outlier | Results may be overfitted or luck-dependent. |

**Warning flags in MC Verdict:**

- `Perf. Outlier` — The historical return was worse than 95% of simulations, meaning the actual results are *below* what random sampling would expect. Investigate why.
- `DD Understated` — Historical drawdowns were better than median simulations. The backtest period may have been unusually favorable.
- `Moderate Tail Risk` — Worst-case simulations show 50–80% drawdown potential.
- `High Tail Risk` — Worst-case simulations show >80% drawdown potential. High risk of ruin.

### Local Report Files

| Location | Contents |
| --- | --- |
| `output/runs/<run_id>/overall_portfolio_summary.csv` | All results across all portfolios, sorted by MC Score. The first 5 columns are run metadata (`run_id`, `data_provider`, `start_date`, `end_date`, `timeframe`) so results are self-describing when combined across runs. |
| `output/runs/<run_id>/analyzer_csvs/<Portfolio>/` | Column-mapped CSVs ready to pass into `report.py` |
| `output/runs/<run_id>/raw_trades/<Portfolio>/` | Per-symbol, per-strategy raw trade logs (when `save_individual_trades=True`) |
| `output/runs/<run_id>/logs/` | Full execution log for the run |

### S3 Reports (if configured)

All output files are also uploaded to `s3://<your-bucket>/<run_id>/`. Each run uses its timestamped folder as the S3 key prefix, so previous results are never overwritten.

---

## Generating Detailed Reports

After a run completes, you can generate a detailed PDF or Markdown report for any individual strategy using `report.py`. This produces equity curves, drawdown charts, trade distribution analysis, and more.

### Single-File Usage

```bash
python report.py output/runs/<run_id>/analyzer_csvs/<Portfolio>/<Strategy>.csv
```

The report is automatically saved to `output/runs/<run_id>/detailed_reports/`. No `--output-dir` flag is needed when working with files inside a run folder.

### Batch Mode — Generate All Reports for a Run

To generate reports for every strategy in a run at once, pass the run directory with `--all`:

```bash
python report.py --all output/runs/<run_id>
```

This finds every `.csv` file recursively under `<run_id>/analyzer_csvs/` and generates one report per file. All reports are saved to `<run_id>/detailed_reports/`. A summary line is printed when complete:

```text
Generated 14 reports in output/runs/2026-03-02_15-12-32/detailed_reports
```

### Examples

```bash
# Generate a report for a specific strategy from your last run
python report.py output/runs/2026-03-02_15-12-32/analyzer_csvs/Nasdaq_100/SMA_Crossover_20d_50d.csv

# Generate a report from a named run
python report.py output/runs/nasdaq-sweep_2026-03-02_15-12-32/analyzer_csvs/Nasdaq_100/SMA_Crossover_20d_50d.csv

# Generate all reports for an entire run at once
python report.py --all output/runs/2026-03-02_15-12-32

# Override where the report is saved
python report.py path/to/strategy.csv --output-dir /path/to/custom/folder

# Set a custom name for the report file and folder
python report.py path/to/strategy.csv --report-name "my-strategy-deep-dive"

# Override the initial equity used for equity curve calculations
python report.py path/to/strategy.csv --equity 250000
```

### All report.py Options

| Flag | Default | Description |
| --- | --- | --- |
| `csv_path` | (required, or use `--all`) | Path to a single backtester-generated CSV |
| `--all RUN_DIR` | — | Path to a run directory; generates reports for all CSVs under `analyzer_csvs/` |
| `--output-dir` | Auto-detected | Root directory for report output. Auto-detected when the CSV is inside `analyzer_csvs/`. |
| `--equity` | 100000 | Initial equity for equity curve calculations |
| `--report-name` | CSV filename | Custom name for the generated report file and its parent folder (single-file mode only) |

> `csv_path` and `--all` are mutually exclusive — use one or the other.

---

## Available Strategies

### Portfolio Mode — Active Strategies

Defined in the `STRATEGIES` dictionary in [strategies.py](strategies.py). Enable or disable strategies by commenting/uncommenting their blocks. All strategy logic lives in [helpers/indicators.py](helpers/indicators.py).

**Currently active (uncommented):**

| Strategy | Description |
| --- | --- |
| SMA Crossover (20d/50d) | Buy when 20-day SMA crosses above 50-day SMA |
| SMA Crossover (50d/200d) | Classic "golden cross" — 50-day SMA crosses above 200-day SMA |

**Available but commented out** (uncomment in `strategies.py` to enable): EMA Crossover variants (Unfiltered, SPY-Only Filter, VIX-Only Filter, SPY+VIX Filter), RSI Mean Reversion, MACD Crossover, Stochastic, OBV Trend, MA Bounce, SMA 200 Trend Filter, MACD+RSI Confirmation, ATR Trailing Stop variants, Bollinger Band variants (Fade, Breakout, Squeeze, with Regime Filter), Donchian Channel Breakout, Keltner Channel Breakout, Chaikin Money Flow, MA Confluence variants (with and without Regime Filter), Daily Overnight Hold with VIX Filter, Hold The Week, Weekend Hold, and sub-daily scalping strategies (1m EMA Scalp, 1m RSI Extreme Fade, 1m BB Squeeze).

### All Available Strategy Logic (helpers/indicators.py)

| Strategy | Description |
| --- | --- |
| SMA Crossover | Buy when fast SMA crosses above slow SMA |
| EMA Crossover | EMA-based crossover with optional SPY and/or VIX regime filters |
| RSI Mean Reversion | Buy when RSI drops below oversold level; exit when it recovers |
| MACD Crossover | Buy when MACD line crosses above signal line |
| MACD + RSI Confirmation | MACD crossover only taken when RSI is not overbought |
| Bollinger Band Fade | Buy when price drops below lower band; exit at middle band |
| Bollinger Band Breakout | Buy when price breaks above upper band |
| Bollinger Band Squeeze | Enter on expansion after a low-volatility squeeze period |
| Bollinger Band Fade w/ SPY Filter | Bollinger fade only when SPY is in an uptrend |
| Stochastic Oscillator | Buy on oversold reading; exit at midpoint |
| OBV Trend | On-Balance Volume trend following with moving average |
| MA Bounce | Buy when price bounces off a moving average |
| SMA 200 Trend Filter | Only trade when price is above the 200-day SMA |
| MA Confluence | Requires alignment of three moving averages for entry |
| MA Confluence w/ Regime Filter | MA Confluence with SPY+VIX regime overlay |
| Donchian Breakout | Buy on new N-day high; exit on M-day low |
| ATR Trailing Stop | Trend entry with an ATR-based trailing stop |
| ATR Trailing Stop w/ Trend Filter | ATR trailing stop only taken above the 200-day SMA |
| Keltner Channel Breakout | Buy on breakout above the Keltner Channel |
| Chaikin Money Flow | Entry and exit based on money flow momentum |
| Daily Overnight Hold w/ VIX Filter | Hold overnight on weekdays only when VIX is below threshold |
| Hold The Week (Tue–Fri) | Calendar-based: buy Tuesday open, sell Friday close |
| Weekend Hold (Fri–Mon) | Calendar-based: buy Friday close, sell Monday open |
| EMA Scalping | Sub-daily EMA crossover for minute-level bars |
| RSI Extreme Fade | Sub-daily RSI extreme reversal for minute-level bars |

---

## Configuration Reference

| Setting | Default | Description |
| --- | --- | --- |
| `data_provider` | `"polygon"` | `"polygon"` or `"norgate"` |
| `upload_to_s3` | `False` | Enable S3 uploads of output files |
| `s3_reports_bucket` | — | S3 bucket name. Requires `upload_to_s3: True`. |
| `start_date` | `"2004-01-01"` | Backtest start date (YYYY-MM-DD) |
| `end_date` | Today | Backtest end date |
| `initial_capital` | `100000.0` | Starting account size in dollars |
| `timeframe` | `"D"` | Bar frequency: `"D"` daily, `"H"` hourly, `"MIN"` minute, `"W"` weekly, `"M"` monthly |
| `timeframe_multiplier` | `1` | For sub-daily bars only — e.g., `5` with `"MIN"` gives 5-minute bars |
| `price_adjustment` | `"total_return"` | `"total_return"` (dividend-adjusted) or `"none"` |
| `benchmark_symbol` | `"SPY"` | Primary benchmark ticker |
| `symbols_to_test` | `['BITB']` | Tickers for single-asset mode |
| `portfolios` | (see config) | Portfolios dict for portfolio mode |
| `allocation_per_trade` | `0.10` | Fraction of equity per new position (0.10 = 10%) |
| `execution_time` | `"open"` | Fill at next-day open price |
| `stop_loss_configs` | `[{"type": "none"}]` | List of stop-loss configurations to test |
| `slippage_pct` | `0.0005` | Slippage as fraction of price (0.0005 = 5 basis points) |
| `commission_per_share` | `0.002` | Commission in dollars per share |
| `min_trades_for_mc` | `50` | Minimum trades required to run Monte Carlo |
| `num_mc_simulations` | `1000` | Number of Monte Carlo simulations per strategy |
| `save_individual_trades` | `True` | Save per-trade CSV logs to `raw_trades/` |
| `save_only_filtered_trades` | `False` | If True, only save logs for strategies passing the display filters |
| `mc_score_min_to_show_in_summary` | `-9999` | Minimum MC score to include in output table |
| `min_pandl_to_show_in_summary` | `-9999` | Minimum P&L % to include in output table |
| `max_acceptable_drawdown` | `1.0` | Maximum drawdown (as a decimal) to include in output table |
| `min_performance_vs_spy` | `-9999` | Minimum outperformance vs SPY to include in output table |
| `min_performance_vs_qqq` | `-9999` | Minimum outperformance vs QQQ to include in output table |
| `show_qqq_losers` | `False` | If False, hides strategies that underperform QQQ |
| `roc_thresholds` | `[0.0, 0.5]` | Rate-of-change thresholds for ROC Momentum strategy |

---

## Data Caching

Downloaded price data is cached locally in `data_cache/` as Parquet files with a 24-hour TTL.

- **First run** for a date range fetches every symbol from Polygon — this is slow for large portfolios (30–60 minutes for Nasdaq-level runs).
- **Subsequent runs** within 24 hours load from disk — typically seconds per symbol.
- To force a fresh fetch, delete the `data_cache/` folder or individual `.parquet` files inside it.
- `data_cache/` is excluded from git via `.gitignore` and should never be committed.

Cache files are named using the pattern `{symbol}_{start}_{end}_{timeframe}_{multiplier}.parquet`. Symbols with special characters (e.g., `I:VIX`) are sanitized for safe filenames.

> **Stale cache warning:** At the start of each run, the backtester scans `data_cache/` for Parquet files older than 7 days and logs a warning if any are found. This is a prompt to delete the folder if your strategies need fresh data — the 24-hour TTL governs in-memory freshness, but on-disk files are not automatically removed after that window.

---

## Adding Custom Strategies

All strategy logic lives in [helpers/indicators.py](helpers/indicators.py). A strategy is a function that:

1. Accepts a DataFrame with `Open`, `High`, `Low`, `Close`, `Volume` columns
2. Returns the same DataFrame with a `Signal` column added

Signal values:

- `1` — Enter / hold long
- `-1` — Exit / go flat
- `0` — No position / no change

```python
# helpers/indicators.py

def my_strategy_logic(df):
    """Buy when price is above the 50-day SMA, exit when below."""
    df['SMA_50'] = df['Close'].rolling(window=50).mean()
    df['Signal'] = 0
    df.loc[df['Close'] > df['SMA_50'], 'Signal'] = 1
    df.loc[df['Close'] <= df['SMA_50'], 'Signal'] = -1
    return df
```

Then register it in `strategies.py`. Import the function at the top and add an entry to the `STRATEGIES` dict:

```python
# strategies.py

from helpers.indicators import my_strategy_logic

STRATEGIES = {
    "My Strategy Name": {
        "logic": my_strategy_logic,
        "dependencies": []  # Add 'spy' or 'vix' if your strategy uses those DataFrames
    },
    # ... other strategies
}
```

**Strategies that use SPY or VIX data** must declare them in `dependencies` and accept `**kwargs`. Create a wrapper function in `strategies.py` following the `strategy_ema_regime` pattern — this ensures the function is pickle-safe for multiprocessing. Pass the external DataFrame via kwargs inside the wrapper, then forward it to the underlying logic function. Always check with your data provider to confirm you're using the correct symbols they expect.

**Using period-based bar counts:** Always use `get_bars_for_period('20d', TIMEFRAME, MULTIPLIER)` rather than hardcoded integers for lookback periods. This ensures strategies work correctly regardless of the configured timeframe (daily, hourly, minute, etc.).

---

## Project Structure

```text
july-backtester/
├── main.py                       # Single entry point — portfolio and single-asset mode
├── strategies.py                 # STRATEGIES dict — enable/disable strategies here
├── config.py                     # All configuration — edit this before running
├── report.py                     # CLI tool to generate PDF/Markdown reports from CSVs
├── requirements.txt              # Python dependencies
├── .env.example                  # Copy to .env and add your Polygon API key
│
├── helpers/
│   ├── indicators.py             # All strategy logic and indicator calculations
│   ├── simulations.py            # Single-asset trade simulation engine
│   ├── portfolio_simulations.py  # Multi-asset portfolio simulation engine
│   ├── monte_carlo.py            # Monte Carlo robustness analysis
│   ├── summary.py                # Report generation, CSV export, S3 upload
│   ├── caching.py                # Local Parquet cache (24h TTL)
│   ├── aws_utils.py              # S3 upload helper; reads API key from env/.env
│   └── timeframe_utils.py        # Bar period conversion utilities
│
├── services/
│   ├── services.py               # Data provider factory (selects Polygon or Norgate)
│   ├── polygon_service.py        # Polygon.io API integration with pagination and caching
│   └── norgate_service.py        # Norgate Data integration
│
├── trade_analyzer/               # Standalone report generation module
│   ├── analyzer.py               # Main entry point for report generation
│   ├── calculations.py           # Metrics and statistics
│   ├── plotting.py               # Chart generation
│   ├── report_generator.py       # PDF/Markdown output
│   └── ...
│
└── tickers_to_scan/              # JSON ticker lists
    ├── nasdaq_100.json
    ├── sp-500.json
    ├── russell_1000.json
    └── ...                       # (and many more)
```

---

## Contributing

Contributions are welcome. To contribute:

1. Fork the repository
2. Create a branch: `git checkout -b feature/my-new-strategy`
3. Add your strategy function to `helpers/indicators.py`
4. Import it and register it in the `STRATEGIES` dictionary in `strategies.py`
5. Run a quick validation on a small portfolio (e.g., `{"Test": ["SPY", "QQQ", "AAPL"]}`) to confirm it runs without errors
6. Open a pull request describing the strategy logic, parameters, and any sample results

Please do not commit API keys, `.env` files, `data_cache/` contents, or the generated `output/` folder. These are all covered by `.gitignore`.

---

## License

[MIT License](LICENSE) — free to use, modify, and distribute. See `LICENSE` file for details.