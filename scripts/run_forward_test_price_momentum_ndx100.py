"""
Forward test runner: Price Momentum strategy on NDX100 universe.

Signal logic (reusing helpers/indicators.py):
  - 6-month ROC (126 trading days) >= 15%
  - Close > 200-day SMA

Output (append-only):
  forward_tests/price_momentum_ndx100_forward_test.csv
  forward_tests/price_momentum_ndx100_daily_summary.md

Run from repo root:
  rtk venv/bin/python scripts/run_forward_test_price_momentum_ndx100.py
"""

import csv
import json
import logging
import os
import sys
from datetime import date, datetime

import pandas as pd

# ── Path setup (per CLAUDE.md scripts/ convention) ──────────────────────────
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)

# ── Project imports (reuse existing logic) ───────────────────────────────────
from helpers.indicators import roc_logic, calculate_sma  # noqa: E402

# ── Constants ────────────────────────────────────────────────────────────────
STRATEGY_NAME = "Price Momentum"
UNIVERSE_NAME = "NDX100"
ROC_PERIOD = 126          # ~6 months of trading days
SMA_PERIOD = 200
ROC_THRESHOLD = 15.0      # percent

NDX100_JSON = os.path.join(_REPO_ROOT, "tickers_to_scan", "nasdaq_100.json")
FORWARD_DIR = os.path.join(_REPO_ROOT, "forward_tests")
CSV_PATH = os.path.join(FORWARD_DIR, "price_momentum_ndx100_forward_test.csv")
MD_PATH = os.path.join(FORWARD_DIR, "price_momentum_ndx100_daily_summary.md")

CSV_COLUMNS = [
    "date", "market_date", "strategy", "universe", "ticker", "company_name",
    "close", "roc_6m", "sma200", "passes_roc_filter", "passes_sma200_filter",
    "signal", "action", "hypothetical_entry_price", "hypothetical_exit_price",
    "position_status", "weight", "daily_pnl", "cumulative_pnl", "notes",
]

# Minimal config for yahoo_service / yfinance
_YF_CONFIG = {"timeframe": "D", "timeframe_multiplier": 1, "price_adjustment": "total_return"}

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)

# ── Company name lookup (best-effort via yfinance .info) ─────────────────────
_NAME_CACHE: dict[str, str] = {}


def _company_name(ticker: str) -> str:
    if ticker in _NAME_CACHE:
        return _NAME_CACHE[ticker]
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).fast_info
        name = getattr(info, "company", "") or ""
    except Exception:
        name = ""
    _NAME_CACHE[ticker] = name
    return name


# ── Data fetch (direct yfinance, no API key needed) ──────────────────────────

def _fetch(ticker: str, lookback_bars: int = 420) -> pd.DataFrame | None:
    """Fetch enough daily bars to compute ROC(126) + SMA(200) safely."""
    try:
        import yfinance as yf
    except ImportError:
        log.error("yfinance not installed. Run: pip install yfinance")
        sys.exit(1)

    # Fetch ~420 calendar days worth (~420 trading days > 200+126+buffer)
    # yfinance period="2y" ~= 504 trading days — more than sufficient
    try:
        df = yf.download(
            ticker,
            period="2y",
            interval="1d",
            auto_adjust=True,
            progress=False,
        )
    except Exception as exc:
        log.warning(f"{ticker}: download failed — {exc}")
        return None

    if df is None or df.empty:
        return None

    # yfinance may return multi-level columns when downloading a single ticker
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # Normalise column names
    df.columns = [c.title() for c in df.columns]
    if "Adj Close" in df.columns:
        df = df.rename(columns={"Adj Close": "Close"})

    keep = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df.columns]
    df = df[keep].copy()
    df = df.dropna(subset=["Close"])

    return df


# ── Signal calculation ────────────────────────────────────────────────────────

def _compute_signals(df: pd.DataFrame) -> dict:
    """
    Run roc_logic and calculate_sma on df, return metric dict for latest bar.
    Returns None values when there is insufficient history.
    """
    if len(df) < max(ROC_PERIOD, SMA_PERIOD) + 1:
        return {"roc_6m": None, "sma200": None, "close": None, "market_date": None}

    # Reuse project helpers — no logic reimplemented here
    df = roc_logic(df.copy(), length=ROC_PERIOD, threshold=ROC_THRESHOLD)
    df = calculate_sma(df, length=SMA_PERIOD)

    row = df.iloc[-1]
    market_date = df.index[-1]
    if hasattr(market_date, "date"):
        market_date = market_date.date()

    return {
        "close": float(row["Close"]),
        "roc_6m": round(float(row["ROC"]), 4) if pd.notna(row.get("ROC")) else None,
        "sma200": round(float(row[f"SMA_{SMA_PERIOD}"]), 4)
            if pd.notna(row.get(f"SMA_{SMA_PERIOD}")) else None,
        "market_date": market_date,
    }


# ── CSV helpers ───────────────────────────────────────────────────────────────

def _csv_exists_and_has_header() -> bool:
    return os.path.isfile(CSV_PATH) and os.path.getsize(CSV_PATH) > 0


def _append_rows(rows: list[dict]) -> None:
    write_header = not _csv_exists_and_has_header()
    with open(CSV_PATH, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        if write_header:
            w.writeheader()
        w.writerows(rows)


# ── Markdown summary ──────────────────────────────────────────────────────────

def _write_summary(run_rows: list[dict], run_date: str, market_date: str) -> None:
    candidates = [r for r in run_rows if r["signal"] == "BUY_CANDIDATE"]
    no_signal = [r for r in run_rows if r["signal"] == "NO_SIGNAL"]
    missing = [r for r in run_rows if r["signal"] == "DATA_MISSING"]

    lines = [
        f"# Price Momentum NDX100 — Forward Test Daily Summary",
        f"",
        f"**Run date:** {run_date}  ",
        f"**Market date:** {market_date}  ",
        f"**Strategy:** {STRATEGY_NAME}  ",
        f"**Universe:** {UNIVERSE_NAME} ({len(run_rows)} tickers scanned)  ",
        f"**Signal logic:** 6m ROC ≥ {ROC_THRESHOLD}% AND Close > SMA{SMA_PERIOD}",
        f"",
        f"---",
        f"",
        f"## Run Statistics",
        f"",
        f"| Metric | Count |",
        f"| --- | --- |",
        f"| BUY_CANDIDATE | {len(candidates)} |",
        f"| NO_SIGNAL | {len(no_signal)} |",
        f"| DATA_MISSING | {len(missing)} |",
        f"| Total scanned | {len(run_rows)} |",
        f"",
        f"---",
        f"",
        f"## BUY_CANDIDATE List",
        f"",
    ]

    if candidates:
        lines.append("| Ticker | Company | Close | ROC 6m (%) | SMA200 | Weight |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for r in sorted(candidates, key=lambda x: float(x["roc_6m"]), reverse=True):
            lines.append(
                f"| {r['ticker']} | {r['company_name']} | {float(r['close']):.2f} "
                f"| {float(r['roc_6m']):.2f} | {float(r['sma200']):.2f} | {r['weight']} |"
            )
    else:
        lines.append("_No tickers passed both filters on this date._")

    lines += [
        f"",
        f"---",
        f"",
        f"## Missing Data",
        f"",
        f"Tickers with insufficient history or fetch errors: "
        f"{', '.join(r['ticker'] for r in missing) or 'None'}",
        f"",
        f"---",
        f"",
        f"_Generated by `scripts/run_forward_test_price_momentum_ndx100.py` — paper trading only, no real trades._",
        f"",
    ]

    # Append to MD (never overwrite)
    if os.path.isfile(MD_PATH):
        lines = [f"\n\n---\n\n*New run appended {run_date}*\n\n"] + lines

    with open(MD_PATH, "a") as f:
        f.write("\n".join(lines))

    log.info(f"Summary written → {MD_PATH}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    run_date = date.today().isoformat()
    log.info(f"=== Price Momentum Forward Test  {run_date} ===")
    log.info(f"Universe: {UNIVERSE_NAME}  |  ROC period: {ROC_PERIOD}d  |  Threshold: {ROC_THRESHOLD}%  |  SMA: {SMA_PERIOD}")

    # Load ticker universe
    with open(NDX100_JSON) as f:
        tickers: list[str] = json.load(f)
    log.info(f"Loaded {len(tickers)} tickers from {os.path.basename(NDX100_JSON)}")

    os.makedirs(FORWARD_DIR, exist_ok=True)

    rows: list[dict] = []

    for i, ticker in enumerate(tickers, 1):
        log.info(f"[{i:03d}/{len(tickers)}] {ticker}")
        df = _fetch(ticker)

        if df is None or df.empty or len(df) < SMA_PERIOD + 10:
            rows.append({
                "date": run_date,
                "market_date": "",
                "strategy": STRATEGY_NAME,
                "universe": UNIVERSE_NAME,
                "ticker": ticker,
                "company_name": "",
                "close": "",
                "roc_6m": "",
                "sma200": "",
                "passes_roc_filter": "",
                "passes_sma200_filter": "",
                "signal": "DATA_MISSING",
                "action": "DATA_MISSING",
                "hypothetical_entry_price": "",
                "hypothetical_exit_price": "",
                "position_status": "N/A",
                "weight": "",
                "daily_pnl": "",
                "cumulative_pnl": "",
                "notes": "Insufficient data or fetch error",
            })
            continue

        metrics = _compute_signals(df)
        close = metrics["close"]
        roc = metrics["roc_6m"]
        sma200 = metrics["sma200"]
        market_date = metrics["market_date"]

        if roc is None or sma200 is None:
            rows.append({
                "date": run_date,
                "market_date": str(market_date) if market_date else "",
                "strategy": STRATEGY_NAME,
                "universe": UNIVERSE_NAME,
                "ticker": ticker,
                "company_name": "",
                "close": f"{close:.4f}" if close else "",
                "roc_6m": "",
                "sma200": "",
                "passes_roc_filter": "",
                "passes_sma200_filter": "",
                "signal": "DATA_MISSING",
                "action": "DATA_MISSING",
                "hypothetical_entry_price": "",
                "hypothetical_exit_price": "",
                "position_status": "N/A",
                "weight": "",
                "daily_pnl": "",
                "cumulative_pnl": "",
                "notes": "ROC or SMA could not be computed (insufficient history)",
            })
            continue

        passes_roc = roc >= ROC_THRESHOLD
        passes_sma = close > sma200
        is_candidate = passes_roc and passes_sma
        signal = "BUY_CANDIDATE" if is_candidate else "NO_SIGNAL"
        action = "PAPER_BUY_CANDIDATE" if is_candidate else "NONE"

        rows.append({
            "date": run_date,
            "market_date": str(market_date),
            "strategy": STRATEGY_NAME,
            "universe": UNIVERSE_NAME,
            "ticker": ticker,
            "company_name": "",          # filled below for candidates
            "close": f"{close:.4f}",
            "roc_6m": f"{roc:.4f}",
            "sma200": f"{sma200:.4f}",
            "passes_roc_filter": str(passes_roc),
            "passes_sma200_filter": str(passes_sma),
            "signal": signal,
            "action": action,
            "hypothetical_entry_price": f"{close:.4f}" if is_candidate else "",
            "hypothetical_exit_price": "",
            "position_status": "OPEN" if is_candidate else "NOT_OPENED",
            "weight": "",                # filled after all tickers
            "daily_pnl": "0.00" if is_candidate else "",
            "cumulative_pnl": "0.00" if is_candidate else "",
            "notes": "",
        })

    # Fill weights for BUY_CANDIDATEs (equal weight)
    candidate_rows = [r for r in rows if r["signal"] == "BUY_CANDIDATE"]
    n_candidates = len(candidate_rows)
    if n_candidates > 0:
        weight = round(1.0 / n_candidates, 4)
        for r in candidate_rows:
            r["weight"] = f"{weight:.4f}"
            # Get company name only for candidates (avoids 100+ info calls)
            r["company_name"] = _company_name(r["ticker"])

    # Determine representative market_date for the summary (mode of non-empty dates)
    dates = [r["market_date"] for r in rows if r["market_date"]]
    summary_market_date = max(dates) if dates else "unknown"

    log.info(f"\nResults: {n_candidates} BUY_CANDIDATE | {sum(1 for r in rows if r['signal']=='NO_SIGNAL')} NO_SIGNAL | {sum(1 for r in rows if r['signal']=='DATA_MISSING')} DATA_MISSING")

    _append_rows(rows)
    log.info(f"Appended {len(rows)} rows → {CSV_PATH}")

    _write_summary(rows, run_date, summary_market_date)

    log.info("Done.")


if __name__ == "__main__":
    main()
