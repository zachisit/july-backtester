"""Central configuration and path resolution for the merge pipeline.

Single source of truth for: the authority cutoff/anchor, the overlap window,
all subsystem folders, audit thresholds, and the required-strategy-asset
allow-list. Every other pipeline module imports from here so there are no
scattered magic constants.
"""
import os
import logging

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

# --- project + subsystem roots ------------------------------------------------
# this file: <ROOT>/src/data/pipeline/paths.py  -> 4 dirnames up == project root
ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), os.pardir, os.pardir, os.pardir)
)
MARKET_DATA = os.path.join(ROOT, "data", "market_data")

POLYGON_RAW = os.path.join(MARKET_DATA, "polygon_raw")
POLYGON_NORMALIZED = os.path.join(MARKET_DATA, "polygon_normalized")
POLYGON_PATCH = os.path.join(MARKET_DATA, "polygon_patch")
MERGED = os.path.join(MARKET_DATA, "merged")
AUDIT = os.path.join(MARKET_DATA, "audit")
LOGS = os.path.join(MARKET_DATA, "logs")
METADATA = os.path.join(MARKET_DATA, "metadata")

# Norgate per-symbol parquet repo (read-only master). env first, then known path.
NORGATE_ROOT = os.environ.get("NORGATE_DATA_ROOT") or \
    r"c:\Users\shard\Light Water Internship\july-backtester-norgate-data\data"

# Cached reference tables produced by the certification scan (reused, not re-scanned).
NORGATE_LAST_DATES_CSV = os.path.join(ROOT, "scripts", "norgate_symbol_last_dates.csv")
POLYGON_REFERENCE_CSV = os.path.join(ROOT, "scripts", "polygon_reference_universe.csv")

# --- authority rule -----------------------------------------------------------
ANCHOR = pd.Timestamp("2026-04-22")          # Norgate's last bar; total-return factor == 1.0 here
PATCH_START = pd.Timestamp("2026-04-23")     # Polygon authoritative from here
OVERLAP_START = pd.Timestamp("2026-04-08")   # pull from here; <= ANCHOR is calibration-only

# --- thresholds ---------------------------------------------------------------
TRAILING_REPULL_DAYS = 5                      # re-pull this many trailing trading days each run
COMPLETENESS_MIN_FRACTION = 0.95             # a day with < 95% of trailing-median symbols FAILS
SPIKE_RETURN_THRESHOLD = 0.50                # |1-day return| > 50% w/o corp action => flag
STALE_FLATLINE_DAYS = 5                       # >= N identical consecutive closes => flag
MIN_LOOKBACK_BARS = 200                       # new listings with < this many bars => insufficient-history

POLYGON_API_KEY = os.environ.get("POLYGON_API_KEY")
POLYGON_BASE = "https://api.polygon.io"

# --- required strategy assets (always kept; never excluded as non-tradeable) ---
# Commodity/bond/FX ETFs + the index symbols strategies depend on.
REQUIRED_STRATEGY_ASSETS = [
    # ETFs (Polygon stocks market)
    "GLD", "SLV", "TLT", "IEF", "HYG", "LQD", "UUP",
    "SPY", "QQQ", "IWM", "DIA", "XLF",
    # indices (Polygon indices market, I: prefix at fetch time)
    "SPX", "NDX", "RUT", "DJI", "OEX", "VIX", "VXN", "TNX",
]

# Polygon security types we treat as tradeable equities/funds (everything else
# is excluded-non-tradeable unless on the required-asset allow-list).
TRADEABLE_POLYGON_TYPES = {"CS", "ETF", "ADRC", "ETN", "ETV", "ETS", "FUND"}
NONTRADEABLE_POLYGON_TYPES = {
    "WARRANT", "RIGHT", "UNIT", "PFD", "SP", "ADRW", "ADRP", "ADRR",
    "BOND", "AGEN", "EQLK", "LT", "BASKET", "OS", "GDR", "NYRS", "OTHER",
}


def ensure_dirs():
    """Create all subsystem folders (idempotent)."""
    for d in (POLYGON_RAW, POLYGON_NORMALIZED, POLYGON_PATCH, MERGED,
              AUDIT, LOGS, METADATA):
        os.makedirs(d, exist_ok=True)


def get_logger(name="merge_pipeline", run_id=None):
    """Console + file logger writing to logs/<run_id or name>.log."""
    ensure_dirs()
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    stamp = run_id or pd.Timestamp.now().strftime("%Y-%m-%d_%H-%M-%S")
    fh = logging.FileHandler(os.path.join(LOGS, f"{name}_{stamp}.log"), encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    return logger


def norgate_path(symbol):
    """Path to a Norgate per-symbol parquet (symbol as stored, e.g. 'AAPL')."""
    return os.path.join(NORGATE_ROOT, f"{symbol}.parquet")
