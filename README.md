# July Backtester v2

A systematic strategy backtesting engine for US equities. Test 20+ built-in technical strategies across individual symbols or large portfolios (Nasdaq, S&P 500, Russell indices, etc.), with Monte Carlo simulation for robustness scoring, benchmark comparison against SPY and QQQ, and automatic report generation.

---

## Table of Contents

1. [What This Tool Does](#what-this-tool-does)
2. [Prerequisites](#prerequisites)
3. [Installation](#installation)
4. [API Key & AWS Setup](#api-key--aws-setup)
5. [Configuration](#configuration)
6. [Running the Backtester](#running-the-backtester)
7. [Understanding the Output](#understanding-the-output)
8. [Available Strategies](#available-strategies)
9. [Configuration Reference](#configuration-reference)
10. [Data Caching](#data-caching)
11. [Adding Custom Strategies](#adding-custom-strategies)
12. [Contributing](#contributing)

---

## What This Tool Does

The backtester takes a strategy (e.g., "buy when the 20-day EMA crosses above the 50-day EMA"), simulates it against historical price data for one or many stocks, and produces a performance report. You can run a single strategy or sweep many strategies simultaneously to find what works.

**Two modes:**

- **Single-Asset Mode** — Tests all 20+ strategies against one or a small list of specific tickers (e.g., just AAPL or BITB). Good for deep-diving a specific stock.
- **Portfolio Mode** — Tests strategies against an entire index or portfolio (e.g., every stock in the Nasdaq 100). Runs in parallel across all your CPU cores. This is the primary research tool.

**What you get out:**

- Total P&L %, Max Drawdown, Sharpe Ratio, Calmar Ratio, Win Rate, Profit Factor
- Performance vs SPY Buy & Hold and QQQ Buy & Hold
- Monte Carlo robustness score (1,000 simulations per strategy to test if results are due to luck)
- Optional: per-trade CSV logs, uploaded to S3

---

## Prerequisites

Before starting, you will need:

1. **Python 3.10 or higher** — [Download here](https://www.python.org/downloads/)
2. **A Polygon.io account** — [Sign up here](https://polygon.io/). A paid plan is required for full historical data (the free tier is limited to 2 years of daily data). The Stocks Starter plan (~$29/month) covers most use cases.
3. **An AWS account** — [Sign up here](https://aws.amazon.com/). Used for two things: securely storing your Polygon API key (AWS Secrets Manager) and optionally uploading reports (S3). A free-tier account is sufficient for Secrets Manager; S3 costs pennies for the report sizes involved.
4. **AWS CLI configured on your machine** — Required for the tool to authenticate with AWS. See setup steps below.

**If you work in our office:** You may already have AWS credentials configured and shared S3/Secrets Manager resources. Check with your team before creating new AWS resources — you likely only need to configure the AWS CLI to point at the existing setup. Ask for the Access Key ID, Secret Access Key, and region.

**For Norgate users:** If you have a [Norgate Data](https://norgatedata.com/) subscription and the Norgate Data Updater installed locally, you can use Norgate as the data provider instead of Polygon. See [Data Provider Settings](#data-provider-settings) below.

---

## Installation

### Step 1 — Clone the Repository

```bash
git clone <repository-url>
cd july-backtester-v2
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

This installs: `pandas`, `numpy`, `tqdm`, `boto3`, `requests`, `python-dotenv`, `pandas-ta`, `orjson`, `pyarrow`.

---

## API Key & AWS Setup

The backtester retrieves your Polygon API key from **AWS Secrets Manager** rather than a plain text file. This keeps your key out of the codebase and environment variables, which is safer when sharing a machine or working in a team.

### Step 1 — Install the AWS CLI

```bash
# macOS (using Homebrew)
brew install awscli

# Windows — download the MSI installer from:
# https://aws.amazon.com/cli/

# Verify installation
aws --version
```

### Step 2 — Configure Your AWS Credentials

```bash
aws configure
```

You will be prompted for four values:

| Prompt | What to Enter |
| --- | --- |
| AWS Access Key ID | Your IAM access key (AWS Console → IAM → Users → Your User → Security credentials → Create access key) |
| AWS Secret Access Key | The corresponding secret key shown at creation time |
| Default region name | `us-east-1` (or the region your team uses) |
| Default output format | `json` |

**Office users:** Get the Access Key ID, Secret Access Key, and region from your team. Do not create new IAM users if credentials already exist for this project.

### Step 3 — Store Your Polygon API Key in AWS Secrets Manager

This creates the secret the tool looks up at runtime.

1. Log in to the [AWS Console](https://console.aws.amazon.com/)
2. Search for **Secrets Manager** in the top search bar and open it
3. Click **Store a new secret**
4. Choose **Other type of secret**
5. Click the **Plaintext** tab under the key/value section
6. Delete any placeholder text and paste your Polygon API key as the only content (plain string, no quotes, no JSON)
7. Click **Next**
8. Give the secret a name — for example: `polygon-api-key`
9. Click through the remaining pages and click **Store**

**Office users:** A shared secret likely already exists. Ask your team for its exact name and skip to Step 4.

### Step 4 — Set the Secret Name in config.py

Open [config.py](config.py) and update this line to match the secret name you used:

```python
"polygon_api_secret_name": "polygon-api-key",  # Must match exactly what you named it in Secrets Manager
```

### Step 5 — (Optional) Set Up an S3 Bucket for Reports

If you want reports automatically uploaded to S3 after each run:

1. In the AWS Console, open **S3**
2. Click **Create bucket**
3. Choose a unique name (e.g., `my-backtester-reports`) and the same region you used above
4. Leave all other settings as default and click **Create bucket**

Then update `config.py`:

```python
"s3_reports_bucket": "my-backtester-reports",
```

If `s3_reports_bucket` is left empty or you do not have S3 access, reports are still saved locally in the `reports/` folder. S3 is optional.

---

## Configuration

All settings live in one file: [config.py](config.py). Open it in any text editor before running.

### Quick Setup Checklist

- [ ] Set `polygon_api_secret_name` to match your AWS secret
- [ ] Set `s3_reports_bucket` (optional)
- [ ] Choose `data_provider`: `"polygon"` or `"norgate"`
- [ ] Set `start_date` and `initial_capital`
- [ ] For single-asset mode: set `symbols_to_test`
- [ ] For portfolio mode: uncomment the portfolios you want in `portfolios`

### Data Provider Settings

```python
"data_provider": "polygon",   # Polygon.io — API key via AWS Secrets Manager
# "data_provider": "norgate", # Norgate Data — requires local Norgate installation
```

### Backtest Period

```python
"start_date": "2004-01-01",                            # How far back to test
"end_date": datetime.now().strftime('%Y-%m-%d'),        # Defaults to today
```

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

### Stop Loss Configuration

```python
"stop_loss_configs": [
    {"type": "none"},                                   # No stop — hold until signal reverses
    # {"type": "percentage", "value": 0.05},            # 5% fixed stop below entry
    # {"type": "atr", "period": 14, "multiplier": 3.0}, # 3x ATR trailing stop
],
```

Include multiple entries to test each strategy with each stop type in the same run.

### Slippage and Commission

```python
"slippage_pct": 0.0005,          # 0.05% slippage per fill (5 basis points)
"commission_per_share": 0.002,   # $0.002 per share commission
```

### Output Filters

These control what appears in the printed summary table. Setting any to `-9999` effectively disables that filter (shows everything).

```python
"mc_score_min_to_show_in_summary": 3,       # Only show strategies with MC score >= 3
"min_pandl_to_show_in_summary": 5.0,        # Only show strategies with P&L >= 5%
"max_acceptable_drawdown": 0.30,            # Only show strategies with max DD <= 30%
"min_performance_vs_spy": 0.0,             # Only show strategies that beat SPY buy-and-hold
```

---

## Running the Backtester

Make sure your virtual environment is activated (`source venv/bin/activate` or the Windows equivalent) before running.

### Portfolio Mode (Primary Use)

Tests all active strategies in `main_portfolio.py` against all portfolios in `config.py`. Uses all CPU cores.

```bash
python main_portfolio.py
```

With an optional run name (added as a prefix to the report folder and S3 path):

```bash
python main_portfolio.py --name "nasdaq-ema-sweep"
```

### Single-Asset Mode

Tests all 20+ strategies against each symbol in `symbols_to_test`.

```bash
python main_single_asset.py
```

> **Note:** `main_single_asset.py` currently defaults to Norgate for data fetching. If you are a Polygon user, use `main_portfolio.py` with a small manual symbol list in `config.py` instead.

### First Run Tips

1. **Validate with one symbol first.** Set `"symbols_to_test": ['SPY']` or `"portfolios": {"Test": ["SPY", "QQQ"]}` and confirm the run completes without errors before testing larger lists.
2. **Watch for AWS errors.** If you see `Could not retrieve AWS secret` in the terminal, your AWS CLI is not configured or the secret name in `config.py` does not match.
3. **The first run is the slowest.** Data is fetched from Polygon and cached locally. Subsequent runs within 24 hours load from disk and are much faster.

---

## Understanding the Output

### Terminal Summary Table

After each portfolio or symbol finishes, a results table is printed to the terminal:

```text
Strategy                      P&L (%)  vs. SPY  Max DD  Calmar  Sharpe  Win Rate  Trades  MC Verdict   MC Score
EMA Crossover w/ SPY+VIX      +142.3%   +58.1%   32.1%    1.82    0.94     54.2%     312   Robust            5
SMA Crossover (20d/50d)        +89.4%   +21.3%   41.5%    1.12    0.71     48.9%     287   Mod. Tail Risk     2
Bollinger Band Fade (20d/2.0)  +34.1%   -49.9%   58.2%    0.41    0.32     41.1%     190   High Tail Risk    -1
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

After each run, the following are saved locally:

| Location | Contents |
| --- | --- |
| `reports/overall_portfolio_summary.csv` | All results sorted by MC Score |
| `trades/<portfolio>/<symbol>_<strategy>_trade_log.csv` | Every individual trade with entry/exit dates, prices, and P&L |

### S3 Reports (if configured)

All report files are also uploaded to `s3://<your-bucket>/<run-timestamp>/`. Each run creates a new timestamped folder so previous results are never overwritten.

---

## Available Strategies

### Single-Asset Mode — All Strategies (enabled by default)

| Strategy | Description |
| --- | --- |
| SMA Crossover (20/50) | Buy when 20-day SMA crosses above 50-day SMA |
| SMA Crossover (50/200) | Classic "golden cross" — 50-day SMA crosses above 200-day SMA |
| RSI Mean Reversion (14/30) | Buy when 14-period RSI drops below 30 (oversold); exit when RSI reaches 50 |
| RSI Mean Reversion (7/20) | Faster version — more trades, shorter average hold |
| MACD Crossover (12/26/9) | Buy when MACD line crosses above signal line |
| Bollinger Band Fade (20/2) | Buy when price drops below lower band; exit at middle band |
| Bollinger Band Breakout (20/2) | Buy when price breaks above upper band |
| Stochastic Oscillator (14/3) | Buy on oversold reading (<20); exit at 50 |
| OBV Trend — Baseline | On-Balance Volume trend following with 20-period moving average |
| OBV w/ Price Confirmation | OBV signal confirmed by price moving average alignment |
| OBV w/ 2-Day Confirmation | OBV signal must hold for 2 days before entry |
| MACD + RSI Confirmation | MACD crossover only taken when RSI is not overbought |
| MA20 Bounce | Buy when price bounces off the 20-day moving average |
| SMA 200 Trend Filter | Only trade when price is above the 200-day SMA |
| Donchian Breakout (20/10) | Buy on new 20-day high; exit on 10-day low |
| ATR Trailing Stop (14/3) | Trend entry with a 3×ATR trailing stop |
| Keltner Channel Breakout | Buy on breakout above Keltner Channel |
| Chaikin Money Flow (20) | Entry and exit based on money flow momentum |
| M-Th Overnight Hold | Calendar-based: hold overnight Monday through Thursday only |
| Weekend Hold | Calendar-based: buy Friday close, sell Monday open |
| ROC Momentum | Buy when rate-of-change exceeds a configurable threshold |

### Portfolio Mode — Active Strategies

Defined in the `STRATEGIES` dictionary at the top of [main_portfolio.py](main_portfolio.py). Enable or disable strategies by commenting/uncommenting their blocks.

**Currently active (uncommented):**

| Strategy | Description |
| --- | --- |
| SMA Crossover (20d/50d) | Portfolio version of the SMA crossover |
| SMA Crossover (50d/200d) | Portfolio version of the golden cross |
| EMA Crossover (Unfiltered) | Pure EMA crossover across the full portfolio |
| EMA Crossover w/ SPY-Only Filter | Only takes trades when SPY is in an uptrend (above its regime MA) |
| EMA Crossover w/ VIX-Only Filter | Only takes trades when VIX is below its threshold (calm market) |
| EMA Crossover w/ SPY+VIX Filter | Requires both SPY trend and low VIX — most conservative, fewest trades |

**Available but commented out** (uncomment in `main_portfolio.py` to enable): RSI, MACD, Bollinger Band variants, Stochastic, OBV, MA Bounce, SMA 200 Trend Filter, Donchian, ATR, Keltner, Chaikin Money Flow, MA Confluence, Overnight Hold, and sub-daily scalping strategies.

---

## Configuration Reference

| Setting | Default | Description |
| --- | --- | --- |
| `data_provider` | `"polygon"` | `"polygon"` or `"norgate"` |
| `polygon_api_secret_name` | — | Name of your AWS Secrets Manager secret |
| `s3_reports_bucket` | — | S3 bucket name. Leave blank to skip uploads. |
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
| `stop_loss_configs` | `[{"type": "none"}]` | List of stop-loss configurations to test |
| `slippage_pct` | `0.0005` | Slippage as fraction of price (0.0005 = 5 basis points) |
| `commission_per_share` | `0.002` | Commission in dollars per share |
| `execution_time` | `"open"` | Fill at next-day open price |
| `min_trades_for_mc` | `50` | Minimum trades required to run Monte Carlo |
| `num_mc_simulations` | `1000` | Number of Monte Carlo simulations per strategy |
| `save_individual_trades` | `True` | Save per-trade CSV logs |
| `save_only_filtered_trades` | `False` | If True, only save logs for strategies passing the display filters |
| `mc_score_min_to_show_in_summary` | `-9999` | Minimum MC score to include in output table |
| `min_pandl_to_show_in_summary` | `-9999` | Minimum P&L % to include in output table |
| `max_acceptable_drawdown` | `1.0` | Maximum drawdown (as a decimal) to include in output table |
| `min_performance_vs_spy` | `-9999` | Minimum outperformance vs SPY to include in output table |
| `min_performance_vs_qqq` | `-9999` | Minimum outperformance vs QQQ to include in output table |

---

## Data Caching

Downloaded price data is cached locally in `data_cache/` as Parquet files with a 24-hour TTL.

- **First run** for a date range fetches every symbol from Polygon — this is slow for large portfolios (30–60 minutes for Nasdaq-level runs).
- **Subsequent runs** within 24 hours load from disk — typically seconds per symbol.
- To force a fresh fetch, delete the `data_cache/` folder or individual `.parquet` files inside it.
- `data_cache/` is excluded from git via `.gitignore` and should never be committed.

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

Then register it in `main_portfolio.py`:

```python
from helpers.indicators import my_strategy_logic

STRATEGIES = {
    "My Strategy Name": {
        "logic": my_strategy_logic,
        "dependencies": []  # Add 'spy' or 'vix' if your strategy uses those DataFrames
    },
    # ... other strategies
}
```

**Strategies that use SPY or VIX data** must declare them in `dependencies` and accept `**kwargs`. Look at `strategy_ema_regime` at the top of `main_portfolio.py` as a template.

---

## Project Structure

```text
july-backtester-v2/
├── main_portfolio.py             # Portfolio mode entry point — primary research tool
├── main_single_asset.py          # Single-asset mode entry point
├── main.py                       # Legacy single-asset runner (v7.3, stable reference)
├── config.py                     # All configuration — edit this before running
├── requirements.txt              # Python dependencies
│
├── helpers/
│   ├── indicators.py             # All strategy logic and indicator calculations
│   ├── simulations.py            # Single-asset trade simulation engine
│   ├── portfolio_simulations.py  # Multi-asset portfolio simulation engine
│   ├── monte_carlo.py            # Monte Carlo robustness analysis
│   ├── summary.py                # Report generation and output formatting
│   ├── caching.py                # Local Parquet cache (24h TTL)
│   ├── aws_utils.py              # AWS Secrets Manager and S3 helpers
│   └── timeframe_utils.py        # Bar period conversion utilities
│
└── services/
    ├── services.py               # Data provider factory (selects Polygon or Norgate)
    ├── polygon_service.py        # Polygon.io API integration with pagination and caching
    └── norgate_service.py        # Norgate Data integration
```

---

## Contributing

Contributions are welcome. To contribute:

1. Fork the repository
2. Create a branch: `git checkout -b feature/my-new-strategy`
3. Add your strategy function to `helpers/indicators.py`
4. Register it in the `STRATEGIES` dictionary in `main_portfolio.py`
5. Run a quick validation on a small portfolio (e.g., `["SPY", "QQQ", "AAPL"]`) to confirm it runs without errors
6. Open a pull request describing the strategy logic, parameters, and any sample results

Please do not commit API keys, AWS credentials, `.env` files, `data_cache/` contents, or generated `reports/` and `trades/` folders. These are all covered by `.gitignore`.

---

## License

[MIT License](LICENSE) — free to use, modify, and distribute. See `LICENSE` file for details.
