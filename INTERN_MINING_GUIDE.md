# Intern Mining Guide — Auto-Research Strategy Selection

**Last updated:** 2026-05-07  
**For:** Forward-test candidate selection from 9,030 backtest runs across 86+ strategy types

---

## What Exists in This Repo

| File / Directory | What It Is | Count |
|---|---|---|
| `output/research_index.csv` | **Single consolidated CSV** — all runs merged, enriched | 9,030 rows, 34 cols |
| `output/runs/*/overall_portfolio_summary.csv` | Individual run result CSVs (source) | 267 files |
| `output/runs/*/llm_verdict.json` | LLM-generated verdict: beats SPY? smooth curve? | 68 files |
| `custom_strategies/private/research_results/pdfs/` | PDF tearsheets organized by track | 87 PDFs |
| `custom_strategies/private/RESEARCH_HANDOFF.md` | Full research log — all rounds, all findings | 300KB |
| `custom_strategies/private/*.py` | Strategy code — entry/exit logic + registered params | 20 files, 137 strategies |
| `custom_strategies/private/strategy_code_lookup.json` | Strategy name → code file + param count index | 137 entries |

---

## Step 1 — Open the Consolidated CSV

**File:** `output/research_index.csv`

Open it in Excel, or filter it with Python (recommended — values include `%` signs):

```python
import pandas as pd

df = pd.read_csv("output/research_index.csv")

# Strip % signs from numeric columns
for col in ["P&L (%)", "Max DD", "Win Rate", "OOS P&L (%)", "vs. SPY (B&H)"]:
    df[col] = pd.to_numeric(df[col].astype(str).str.replace('%','').str.replace('+',''), errors='coerce')

df["Sharpe"] = pd.to_numeric(df["Sharpe"], errors="coerce")
df["Trades"] = pd.to_numeric(df["Trades"], errors="coerce")

print(f"Total rows: {len(df)}")
print(df.columns.tolist())
```

### Column Reference

| Column | Type | Notes |
|---|---|---|
| `run_id` | str | Run folder name (e.g. `ec-vix-session9_2026-05-06`) |
| `Strategy` | str | Exact registered strategy name |
| `Portfolio` | str | Universe tested on (e.g. `NDX+Energy+Defense`) |
| `Sharpe` | float | Annualized Sharpe ratio |
| `Max DD` | str `%` | Maximum drawdown percentage |
| `P&L (%)` | str `%` | Total return over backtest period |
| `vs. SPY (B&H)` | str `%` | Outperformance vs SPY buy-and-hold |
| `Profit Factor` | float | Gross profit / gross loss |
| `Win Rate` | str `%` | % of trades that were profitable |
| `Trades` | int | Total number of trades |
| `OOS P&L (%)` | str `%` | Out-of-sample P&L (WFA holdout) |
| `WFA Verdict` | str | `Pass` / `Likely Overfitted` / `N/A` |
| `Rolling WFA` | str | `Pass (3/3)` / `Pass (2/3)` / `Fail` / `N/A` |
| `MC Score` | int | Monte Carlo score: -999 to +5 |
| `Max Rcvry (d)` | int | Longest recovery from any drawdown, calendar days |
| `llm_beats_spy` | bool | LLM verdict: strategy return > SPY B&H |
| `llm_smooth_verdict` | str | `SMOOTH` / `ACCEPTABLE` / `ROUGH` |
| `llm_longest_flat_months` | int | Longest plateau without a new equity high |
| `code_file` | str | Relative path to the Python strategy file |
| `param_count` | int | Number of tunable parameters in the strategy |

---

## Step 2 — Apply the Filter

Run this in Python to get the short list:

```python
import pandas as pd

df = pd.read_csv("output/research_index.csv")
for col in ["Max DD", "Sharpe", "OOS P&L (%)"]:
    df[col] = pd.to_numeric(df[col].astype(str).str.replace('%','').str.replace('+',''), errors='coerce')
df["Trades"] = pd.to_numeric(df["Trades"], errors="coerce")

# ── MAIN FILTER ─────────────────────────────────────────────────────────────
filtered = df[
    (df["WFA Verdict"] == "Pass") &
    (df["Sharpe"] > 0.5) &
    (df["Max DD"] < 30.0) &
    (df["Trades"] > 50) &
    # Exclude Bitcoin and 4-hour strategies (different asset class / timeframe)
    (~df["Strategy"].str.startswith("BTC")) &
    (~df["Strategy"].str.contains("4H")) &
    # Exclude sensitivity sweep variants — keep only base-param runs
    (~df["Strategy"].str.contains(r"\[.*=.*\]", regex=True))
]

print(f"Passing rows: {len(filtered)}")
print(f"Unique strategies: {filtered['Strategy'].nunique()}")

# Sort by Sharpe descending
top = filtered.sort_values("Sharpe", ascending=False)
print(top[["run_id", "Strategy", "Sharpe", "Max DD", "Trades", "WFA Verdict",
           "Rolling WFA", "OOS P&L (%)", "llm_smooth_verdict", "param_count",
           "code_file"]].to_string())
```

**Expected output:** ~186 rows, ~86 unique strategy names.

### Tighter filter for confirmed champions only

To narrow to the 14 strategies confirmed across 9+ universes (the most robust ones):

```python
CONFIRMED_CHAMPIONS = [
    "Relative Momentum (13w vs SPY) Weekly + SMA200",
    "BB Weekly Breakout (20w/2std) + SMA200",
    "Williams R Weekly Trend (above-20) + SMA200",
    "Price Momentum (6m ROC, 15pct) + SMA200",
    "MA Bounce (50d/3bar) + SMA200 Gate",
    "RSI Weekly Trend (55-cross) + SMA200",
    "MA Confluence (10/20/50) Fast Exit",
    "Donchian Breakout (40/20)",
    "EC-VIX-27: WR70 SMA120 minimal-entry-25 vix-95th VIX-pct",
    "EC-VIX-25: WR70 SMA120 minimal-entry-25 vix-85th VIX-pct",
    "EC-VIX-23: WR70 SMA120 minimal-entry-22 VIX-pct",
    "EC-VIX-22: WR70 SMA120 minimal-entry-25 VIX-pct",
]

champions = df[df["Strategy"].isin(CONFIRMED_CHAMPIONS)]
print(champions[["Strategy", "Sharpe", "Max DD", "Trades", "OOS P&L (%)",
                  "llm_smooth_verdict", "param_count"]].to_string())
```

---

## Step 3 — Inspect the Equity Curve (PDFs)

PDF tearsheets are organized by research track:

```
custom_strategies/private/research_results/pdfs/
├── ec_daily/       ← EC track (EC-R20 through EC-R53, EMA/MA variants)
├── ec_vix/         ← EC-VIX track champions (EC-VIX-8, 22, 23, 25, 27, 28)
├── weekly_equity/  ← Weekly confirmed champions (Donchian, MA Bounce, RSI, etc.)
├── bitcoin_daily/  ← BTC strategies (skip for equity workflow)
└── 4h_polygon/     ← 4H Polygon strategies (skip for equity workflow)
```

### PDF naming convention

PDFs are named after the run ID prefix + strategy name:
- `EC-VIX-27_WR70_SMA120_minimal-entry-25_vix-95th_VIX-pct.pdf`
- `MA_Bounce_50d_3bar_+_SMA200_Gate.pdf`
- `Williams_R_Weekly_Trend_above-20_+_SMA200.pdf`

Not every strategy has a PDF — they were generated selectively for top candidates. If a PDF is missing, you can regenerate one (see Step 5 below).

### What to look for in the equity curve

| What you see | Verdict |
|---|---|
| Gradual upward slope with steady compounding | **GOOD** — keep it |
| Single large spike near the end (recent market rally) | **FLAG** — check if the spike is unrealized P&L from open positions |
| Flat for 2+ years, then sudden jump | **BAD** — plateau followed by spike. Reject. |
| Tracks SPY but doesn't beat it | **BAD** — fails requirement 1 |
| Goes straight down in 2022 bear market and never recovers | **BAD** — regime-dependent |
| Smooth above SPY line the entire period | **BEST** — production candidate |

**Important caveat on recent "straight up" curves:**  
The backtester closes open positions at the final bar. Any "vertical" move in the last 6 months of an equity curve may be 90%+ unrealized P&L from still-open positions. Check the tearsheet's trade log for `ExitReason = "End of Backtest"` entries. If those trades account for >20% of the final year's gains, the visual curve is misleading.

---

## Step 4 — Find the Strategy Code

### Method 1: Look up directly

```python
import json

with open("custom_strategies/private/strategy_code_lookup.json") as f:
    lookup = json.load(f)

strategy_name = "EC-VIX-27: WR70 SMA120 minimal-entry-25 vix-95th VIX-pct"
info = lookup.get(strategy_name)
print(info)
# → {"code_file": "custom_strategies/private/ec_vix_strategies.py", "param_count": 9}
```

### Method 2: Check the CSV

The `code_file` and `param_count` columns in `research_index.csv` contain this directly.

### Method 3: Search by file

| Research track | Strategy file |
|---|---|
| EC-VIX track (VIX-adaptive) | `custom_strategies/private/ec_vix_strategies.py` |
| EC smooth-curve variants (EC-R53–R81, EC-TLT) | `custom_strategies/private/smooth_curve_strategies.py` |
| Weekly champions (Rel Momentum, BB, Williams R, Stochastic) | `custom_strategies/private/round34_strategies.py` |
| MA Bounce, ATR trailing stop, MACD+RSI | `custom_strategies/private/research_strategies_v4.py` |
| MA Confluence Fast/Full Exit | `custom_strategies/private/research_strategies_v3.py` |
| Price Momentum, NR7 | `custom_strategies/private/round9_strategies.py` |
| Donchian variants | `custom_strategies/private/research_strategies_v2.py` |
| RSI Weekly, MACD Weekly | `custom_strategies/private/round13_strategies.py` |
| Relative Momentum Weekly | `custom_strategies/private/round36_strategies.py` |

### Counting parameters

`param_count` in the CSV = number of keys in the strategy's `params={}` dict.  
**Rule**: strategies with more than 5 parameters are at higher overfitting risk. Flag but don't auto-reject — some params are structural (e.g. SMA length) rather than tuned.

To count manually: open the code file, find the `@register_strategy(name="...", params={...})` block for your strategy, count the keys.

---

## Step 5 — Rerun on Single Stocks

The backtester is designed to run strategy(s) across a basket. To validate on 8-10 individual tickers:

### 1. Edit `config.py`

Find the `portfolios` key and replace with:

```python
"portfolios": {
    "My Validation Set": ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "JPM"]
},
```

### 2. Set the strategy filter

Add/change the `strategies` key to run only the one strategy you're validating:

```python
"strategies": ["EC-VIX-27: WR70 SMA120 minimal-entry-25 vix-95th VIX-pct"],
```

### 3. Match the original data provider

The confirmed champions were run with Norgate (`data_provider = "parquet"` in the run metadata = Norgate parquet exports). If you only have Yahoo Finance:

```python
"data_provider": "yahoo",
```

Results will differ slightly from the research runs (Yahoo vs Norgate data quality) but the signal logic is identical.

### 4. Set dates

Use the same period as the original research run to ensure comparability:

```python
"start_date": "2004-01-01",
"end_date": "2026-05-07",   # or datetime.now() for latest
```

### 5. Run

```bash
rtk python main.py --name "validation-ec-vix27-aapl-8stocks" --verbose
```

Output appears in `output/runs/validation-ec-vix27-aapl-8stocks_<timestamp>/`.

### What to expect on single stocks

- Sharpe will be much lower than the portfolio run (portfolio diversification is gone)
- A strategy that showed Sharpe 1.8 on 44 stocks might show Sharpe 0.3-0.7 on a single stock
- This is expected and normal — you're checking that the *signal* works, not reproducing the portfolio result
- **Green flag**: WFA Pass on at least 5/8 single-stock tests
- **Red flag**: WFA "Likely Overfitted" on 5+ of the 8 stocks

---

## Step 6 — What to Report

For each strategy that survives all filters, fill in this table:

| Field | Where to find it |
|---|---|
| Strategy name | `research_index.csv` → `Strategy` |
| Sharpe (portfolio) | `research_index.csv` → `Sharpe` |
| Max DD% | `research_index.csv` → `Max DD` |
| Total trades | `research_index.csv` → `Trades` |
| WFA verdict | `research_index.csv` → `WFA Verdict` |
| Rolling WFA | `research_index.csv` → `Rolling WFA` |
| OOS P&L% | `research_index.csv` → `OOS P&L (%)` |
| Beats SPY | `research_index.csv` → `llm_beats_spy` or `vs. SPY (B&H)` |
| Equity curve assessment | Visual PDF review → Gradual / Spike-driven / Flat |
| Plateau length | `research_index.csv` → `llm_longest_flat_months` (in months) |
| Param count | `research_index.csv` → `param_count` |
| Code file | `research_index.csv` → `code_file` |
| Single-stock WFA pass rate | Your validation run result |

---

## Quick Reference: Confirmed Champions (as of 2026-05-07)

These have been validated across 9 universes and are the strongest forward-test candidates.

### Weekly Timeframe (Best Risk-Adjusted)

| Strategy | Sharpe | Max DD | WFA | Trades | Code File |
|---|---|---|---|---|---|
| Relative Momentum (13w vs SPY) Weekly + SMA200 | 2.08 | ~45% | Pass 3/3 | 831 | `round36_strategies.py` |
| BB Weekly Breakout (20w/2std) + SMA200 | 2.08 | ~45% | Pass 3/3 | 798 | `round34_strategies.py` |
| Williams R Weekly Trend (above-20) + SMA200 | 1.94 | ~45% | Pass 3/3 | 799 | `round34_strategies.py` |
| Price Momentum (6m ROC, 15pct) + SMA200 | 1.87 | ~45% | Pass 3/3 | ~800 | `round9_strategies.py` |
| MA Bounce (50d/3bar) + SMA200 Gate | 1.92 | ~45% | Pass 3/3 | ~750 | `research_strategies_v4.py` |
| RSI Weekly Trend (55-cross) + SMA200 | 1.85 | ~45% | Pass 3/3 | ~800 | `round13_strategies.py` |

_Note: MaxDD on 44 NDX symbols ≈ 45%. On DJI 30 universe: 19-23%. Use `sectors_dji_combined.json` for lower drawdown at cost of some Sharpe._

### EC-VIX Track (Newer — NDX+Energy+Defense Universe)

| Strategy | Sharpe | Max DD | WFA | Trades | Beats SPY | Smooth |
|---|---|---|---|---|---|---|
| EC-VIX-27: WR70 SMA120 minimal-entry-25 vix-95th | 0.83 | 24.52% | Pass 3/3 | 3,636 | Yes (+3259pp) | ACCEPTABLE |
| EC-VIX-25: WR70 SMA120 minimal-entry-25 vix-85th | 0.83 | 23.24% | Pass 3/3 | 3,792 | Yes (+3177pp) | ACCEPTABLE |
| EC-VIX-23: WR70 SMA120 minimal-entry-22 | 0.84 | 21.12% | Pass 3/3 | 3,844 | Yes (+3083pp) | ACCEPTABLE |
| EC-VIX-22: WR70 SMA120 minimal-entry-25 | 0.81 | 21.50% | Pass 3/3 | 3,892 | Yes (+2795pp) | ACCEPTABLE |

_Note: EC-VIX strategies use a 46-symbol NDX+Energy+Defense universe and require VIX data. Max recovery for all is ~650 days — passes the <365-day hard requirement only marginally. Visual PDF inspection is essential before forward-testing._

---

## Key Warnings for Interns

1. **Do not cherry-pick on single symbols.** AAPL results alone mean nothing. Always validate on 6+ symbols minimum before drawing conclusions.

2. **Portfolio Sharpe ≠ single-stock Sharpe.** A strategy showing Sharpe 1.9 on 44 NDX stocks will show Sharpe 0.3-0.6 on a single stock. This is not the strategy failing — it's diversification being removed.

3. **Check unrealized P&L on recent runs.** Any equity curve that "goes vertical" in the last 6 months likely contains open positions not yet exited. See the `ExitReason = "End of Backtest"` diagnostic in RESEARCH_HANDOFF.md lines 43-87.

4. **More parameters ≠ better strategy.** Strategies with >5 parameters that pass WFA are suspicious — they may have been inadvertently tuned to the in-sample period. Prefer strategies with 3-5 structural parameters.

5. **The `llm_smooth_verdict` column covers only 99 rows.** For strategies without LLM verdict, check the PDF manually or look in the round markdown files under `research_results/`.

6. **Do not rerun the full research loop.** Use `config.py` `"strategies": [...]` to run only the specific strategy you want to validate. Running all 137 strategies takes hours and is unnecessary.

---

## Regenerating a PDF Tearsheet

If a strategy doesn't have a PDF in `research_results/pdfs/`, you can generate one from any run:

```bash
# For a run with one strategy × one portfolio:
rtk python report.py --all output/runs/<run_id>

# For a specific strategy in a multi-strategy run:
rtk python report.py output/runs/<run_id>/analyzer_csvs/<Portfolio>/<StrategyName>.csv \
    --output-dir output/reports/<unique_name> \
    --report-name <unique_name>
```

Find the run_id from `research_index.csv` → `run_id` column. The analyzer CSVs are in `output/runs/<run_id>/analyzer_csvs/<Portfolio>/`.

---

## Rebuilding the Research Index

If new runs are added, regenerate `output/research_index.csv`:

```bash
rtk python scripts/build_research_index.py
```

This takes ~30 seconds and consolidates all 267 (or more) run CSVs automatically.
