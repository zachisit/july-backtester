"""helpers/rule_based_universe.py

Rule-based point-in-time universe from the delisted-inclusive Parquet corpus.

The problem this solves
-----------------------
A survivorship-free backtest needs to know *what was investable on date D*.
The usual answer is an index roster (S&P 500 members as of D), which is
vendor-locked: reconstructing it needs ``norgatedata.index_constituent_
timeseries()``, which needs a live Norgate Data Updater — Windows-only, and
gone once a subscription lapses.

But "reconstruct the index roster" was never the actual requirement. What a
systematic backtest needs is *a defensible, survivorship-free, point-in-time
investable set*. An index roster is one way to get one. A **rule** is another,
and it needs no membership data at all::

    universe(D) = { s : s has bars on D
                    and close(s, D)             >= min_price
                    and dollar_volume_20d(s, D) >= min_dollar_volume
                    and history(s, D)           >= min_bars }

optionally capped to the top N by dollar volume for a fixed-size universe
comparable across dates (a liquidity-ranked stand-in for an index's size
screen).

Why this is defensible
----------------------
* **No survivorship bias by construction.** The corpus carries delisted
  securities named ``TICKER-YYYYMM`` — Bear Stearns is ``BSC-200805``,
  Lehman ``LEHMQ-201203``, Enron ``ENRNQ-200411``. They are present with the
  dates they failed, and drop out of the universe on their real last bar.
* **No look-ahead by construction.** Every test reads only bars at or before
  ``D``. A company that IPO'd later simply is not there.
* **Reproducible.** Deterministic from committed data. No vendor call, no
  scraped anchors, no hand-extracted PDFs.
* **Auditable.** Every membership decision is a threshold on observable data,
  not a claim about what a roster said.

What it is NOT
--------------
This is not the S&P 500, the Russell 3000, or any index. If a strategy's thesis
depends on index membership *itself* — reconstitution flow, inclusion effects,
benchmark-relative mandates — this does not substitute. **Results produced on
this universe must say so.**

Ticker reuse
------------
Resolution is by **security**, never by bare ticker string. ``WB`` is Wachovia
until 2008 (``WB-200812``) and Weibo from 2014 (``WB``); ``V`` was Vivendi
(``V-200608``) before Visa (``V``). This module returns security IDs, which the
Parquet provider resolves by exact filename — sidestepping its ambiguous
bare-ticker fallback entirely.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime

import pandas as pd

logger = logging.getLogger(__name__)

#: ``TICKER-YYYYMM`` marks a security that stopped trading in that month.
_DELISTED_RE = re.compile(r"^(?P<ticker>.+)-(?P<yyyymm>\d{6})$")

DEFAULTS = {
    "universe_min_price": 5.0,
    "universe_min_dollar_volume": 1_000_000.0,
    "universe_min_bars": 252,
    "universe_top_n": None,
    "universe_adv_window": 20,
    "universe_exclude_prefixes": ("$", "#"),
    "universe_exclude_symbols": (),
}

#: Broad-market and sector ETFs rank near the top on dollar volume in every era
#: (SPY, QQQ and IWM lead the 2004-2024 top-500 in that order). They are
#: genuinely investable, so this is NOT a default exclusion — but a
#: *stock-selection* strategy run on a universe containing SPY can quietly end
#: up holding the index it is being benchmarked against, which flatters it in a
#: way nothing in the metrics reveals. Pass this as ``universe_exclude_symbols``
#: for single-name research.
#:
#: This is a starting list, not an exhaustive ETF classification — the corpus
#: carries no security-type flag, so there is no reliable programmatic test.
COMMON_ETFS = (
    "SPY", "QQQ", "IWM", "DIA", "EEM", "EFA", "GLD", "SLV", "TLT", "IEF",
    "HYG", "LQD", "VTI", "VOO", "IVV", "XLF", "XLE", "XLK", "XLV", "XLI",
    "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC", "VNQ", "USO", "UNG",
)

#: The corpus is not all equities. ``$`` marks index series ($NYA, $DJITR,
#: $SP900TR — 1,160 of them) and ``#`` marks market-breadth / advance-decline
#: series (#NYSEAD, #SP1500AD — 455 more). They carry price and volume columns,
#: so nothing about the liquidity screen rejects them, and their notional
#: "dollar volume" is large enough that they otherwise dominate every top-N
#: ranking — a top-100 universe came back as almost entirely indices. They are
#: not investable and must be excluded before ranking.
NON_TRADEABLE_PREFIXES = ("$", "#")


def is_tradeable(security: str, exclude_prefixes=NON_TRADEABLE_PREFIXES) -> bool:
    """False for index / breadth series that are priced but not investable."""
    return not str(security).startswith(tuple(exclude_prefixes))


# ---------------------------------------------------------------------------
# Security identity
# ---------------------------------------------------------------------------

def parse_security(stem: str) -> tuple[str, str | None]:
    """Split a security ID into ``(bare_ticker, delisted_yyyymm | None)``.

    ``"BSC-200805" -> ("BSC", "200805")``; ``"AAPL" -> ("AAPL", None)``.

    Only a 6-digit suffix counts, so genuine hyphenated tickers (share classes
    like ``BRK-A``, ``MER-K``) are not mistaken for delisting stamps.
    """
    m = _DELISTED_RE.match(stem)
    if m:
        return m.group("ticker"), m.group("yyyymm")
    return stem, None


def is_delisted(stem: str) -> bool:
    """True if the security ID carries a delisting stamp."""
    return parse_security(stem)[1] is not None


# ---------------------------------------------------------------------------
# Span index
# ---------------------------------------------------------------------------

def _naive(ts) -> pd.Timestamp:
    """Normalise to a tz-naive Timestamp.

    The corpus is not uniform — some securities carry tz-aware timestamps and
    some do not. Mixing them makes the span index uncomparable
    ("Cannot compare tz-naive and tz-aware timestamps") the moment you filter
    by date, which is the only thing this index exists to do.
    """
    ts = pd.Timestamp(ts)
    return ts.tz_localize(None) if ts.tz is not None else ts


def _read_span(path: str) -> tuple[pd.Timestamp, pd.Timestamp, int] | None:
    """First bar, last bar and row count, from Parquet metadata only.

    Reads row-group statistics rather than the data, which is what makes a
    36k-file scan tractable.

    **The trap:** ``Datetime`` is not column 0 in these files — the column order
    is ``Open, High, Low, Close, Volume, Datetime`` because ``Datetime`` is the
    pandas index. Locating it by position yields float OHLC values interpreted
    as nanosecond timestamps, i.e. silently-1970 dates. It is located by *name*
    here, and that is deliberate.
    """
    import pyarrow.parquet as pq

    try:
        md = pq.ParquetFile(path).metadata
    except Exception as exc:  # noqa: BLE001 — a corrupt file must not kill the scan
        logger.debug("span scan: unreadable %s: %s", path, exc)
        return None

    if md.num_rows == 0:
        return None

    names = [md.schema.column(i).name for i in range(md.num_columns)]
    if "Datetime" not in names:
        return None
    dt_idx = names.index("Datetime")

    lo, hi = None, None
    for rg in range(md.num_row_groups):
        stats = md.row_group(rg).column(dt_idx).statistics
        if stats is None or not stats.has_min_max:
            # No statistics — fall back to reading just the timestamp column.
            try:
                col = pq.read_table(path, columns=["Datetime"])["Datetime"]
                series = pd.to_datetime(col.to_pandas())
                return _naive(series.min()), _naive(series.max()), md.num_rows
            except Exception:  # noqa: BLE001
                return None
        rg_lo, rg_hi = _naive(stats.min), _naive(stats.max)
        lo = rg_lo if lo is None else min(lo, rg_lo)
        hi = rg_hi if hi is None else max(hi, rg_hi)

    if lo is None or hi is None:
        return None
    return lo, hi, md.num_rows


def build_span_index(data_dir: str, cache_path: str | None = None,
                     force: bool = False) -> pd.DataFrame:
    """Build (or load) the ``security -> [first_bar, last_bar, n_bars]`` index.

    Scanning 36k Parquet footers takes tens of seconds, so the result is cached.
    Without this index, resolving a universe for a single date would re-open
    every file in the corpus.

    Returns a DataFrame indexed by security ID with columns
    ``ticker``, ``delisted``, ``first_bar``, ``last_bar``, ``n_bars``.
    """
    if cache_path and os.path.exists(cache_path) and not force:
        return pd.read_parquet(cache_path)

    if not os.path.isdir(data_dir):
        raise FileNotFoundError(
            f"Parquet corpus not found at '{data_dir}'. This is a git submodule — "
            "run 'git submodule update --init parquet_data'."
        )

    rows = []
    files = sorted(f for f in os.listdir(data_dir) if f.endswith(".parquet"))
    logger.info("Building span index over %d securities in %s", len(files), data_dir)

    for i, fname in enumerate(files):
        stem = fname[: -len(".parquet")]
        span = _read_span(os.path.join(data_dir, fname))
        if span is None:
            continue
        first, last, n = span
        ticker, delisted = parse_security(stem)
        rows.append({
            "security": stem, "ticker": ticker, "delisted": delisted,
            "first_bar": first, "last_bar": last, "n_bars": n,
        })
        if (i + 1) % 5000 == 0:
            logger.info("  span index: %d/%d", i + 1, len(files))

    idx = pd.DataFrame(rows).set_index("security").sort_index()

    if cache_path:
        os.makedirs(os.path.dirname(os.path.abspath(cache_path)), exist_ok=True)
        idx.to_parquet(cache_path)
    return idx


# ---------------------------------------------------------------------------
# Universe resolution
# ---------------------------------------------------------------------------

def _liquidity_at(path: str, as_of: pd.Timestamp, adv_window: int):
    """``(close, dollar_volume, n_bars)`` as of *as_of*, using only bars <= as_of.

    Returns ``None`` when the security has no bar on or before ``as_of``.
    """
    try:
        df = pd.read_parquet(path, columns=["Close", "Volume"])
    except Exception as exc:  # noqa: BLE001
        logger.debug("liquidity: unreadable %s: %s", path, exc)
        return None

    if df.empty:
        return None
    idx = df.index
    if getattr(idx, "tz", None) is not None:
        df.index = idx.tz_localize(None)

    # Strictly causal: nothing after as_of is visible.
    df = df.loc[df.index <= as_of]
    if df.empty:
        return None

    window = df.tail(adv_window)
    dollar_volume = float((window["Close"] * window["Volume"]).mean())
    return float(df["Close"].iloc[-1]), dollar_volume, len(df)


def resolve_universe(as_of, config: dict | None = None,
                     span_index: pd.DataFrame | None = None) -> list[str]:
    """Return the security IDs investable as of *as_of*.

    Parameters
    ----------
    as_of : str | datetime | pd.Timestamp
        The evaluation date. Only bars at or before this date are read.
    config : dict, optional
        Reads ``universe_min_price``, ``universe_min_dollar_volume``,
        ``universe_min_bars``, ``universe_top_n``, ``universe_adv_window``,
        and ``parquet_data_dir``. Missing keys fall back to :data:`DEFAULTS`.
    span_index : DataFrame, optional
        Prebuilt index; built (and cached) on demand when omitted.

    Returns
    -------
    list[str]
        Security IDs (e.g. ``["AAPL", "BSC-200805", ...]``), sorted by
        descending dollar volume when ``universe_top_n`` is set, else
        alphabetically.
    """
    config = config or {}
    as_of = pd.Timestamp(as_of)
    if as_of.tz is not None:
        as_of = as_of.tz_localize(None)

    def _cfg(key):
        val = config.get(key, DEFAULTS[key])
        return DEFAULTS[key] if val is None and key != "universe_top_n" else val

    min_price = _cfg("universe_min_price")
    min_dollar_volume = _cfg("universe_min_dollar_volume")
    min_bars = _cfg("universe_min_bars")
    top_n = config.get("universe_top_n", DEFAULTS["universe_top_n"])
    adv_window = _cfg("universe_adv_window")

    data_dir = config.get("parquet_data_dir", "parquet_data/data")
    if not os.path.isabs(data_dir):
        data_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), data_dir
        )

    if span_index is None:
        cache = os.path.join(os.path.dirname(data_dir), ".span_index.parquet")
        span_index = build_span_index(data_dir, cache_path=cache)

    # --- Stage 0: drop non-investable series ($ indices, # breadth) ---------
    exclude_prefixes = config.get(
        "universe_exclude_prefixes", DEFAULTS["universe_exclude_prefixes"]
    )
    if exclude_prefixes:
        tradeable = span_index.index.map(
            lambda s: is_tradeable(s, exclude_prefixes)
        )
        span_index = span_index[list(tradeable)]

    # Explicit symbol exclusions, matched on the BARE ticker so a delisted
    # variant of an excluded name is excluded too.
    exclude_symbols = {
        s.upper() for s in config.get(
            "universe_exclude_symbols", DEFAULTS["universe_exclude_symbols"]
        )
    }
    if exclude_symbols:
        span_index = span_index[
            ~span_index["ticker"].str.upper().isin(exclude_symbols)
        ]

    # --- Stage 1: cheap span filter (was it trading, and long enough?) -------
    alive = span_index[
        (span_index["first_bar"] <= as_of) & (span_index["last_bar"] >= as_of)
    ]
    # min_bars is in *trading* days; require at least that many calendar days
    # of listed history before paying to read the file. 7/5 converts trading
    # days to calendar days; the exact bar count is checked in stage 2.
    if min_bars:
        need = pd.Timedelta(days=int(min_bars * 7 / 5))
        alive = alive[(as_of - alive["first_bar"]) >= need]

    logger.info("rule universe %s: %d securities alive after span filter",
                as_of.date(), len(alive))

    # --- Stage 2: liquidity screen (reads bars, strictly <= as_of) ----------
    rows = []
    for security in alive.index:
        stats = _liquidity_at(
            os.path.join(data_dir, f"{security}.parquet"), as_of, adv_window
        )
        if stats is None:
            continue
        close, dollar_volume, n_bars = stats
        if close < min_price or dollar_volume < min_dollar_volume:
            continue
        if min_bars and n_bars < min_bars:
            continue
        rows.append((security, dollar_volume))

    if top_n:
        rows.sort(key=lambda r: r[1], reverse=True)
        rows = rows[: int(top_n)]
        return [r[0] for r in rows]

    return sorted(r[0] for r in rows)


# ---------------------------------------------------------------------------
# Portfolio-spec parsing  ("rule:us_liquid_1000")
# ---------------------------------------------------------------------------

#: Named presets usable as ``"rule:<name>"`` in ``config["portfolios"]``.
PRESETS = {
    "us_liquid_1000": {"universe_top_n": 1000},
    "us_liquid_500":  {"universe_top_n": 500},
    "us_liquid_100":  {"universe_top_n": 100},
    "us_all":         {"universe_top_n": None},
}


def is_rule_spec(spec) -> bool:
    """True if *spec* is a ``"rule:..."`` portfolio specification."""
    return isinstance(spec, str) and spec.lower().startswith("rule:")


def parse_rule_spec(spec: str) -> dict:
    """Turn ``"rule:us_liquid_1000"`` into config overrides.

    Also accepts an inline top-N — ``"rule:top250"`` — so a one-off size does
    not need a preset.
    """
    name = spec.split(":", 1)[1].strip().lower()
    if name in PRESETS:
        return dict(PRESETS[name])
    m = re.fullmatch(r"top(\d+)", name)
    if m:
        return {"universe_top_n": int(m.group(1))}
    raise ValueError(
        f"Unknown rule universe '{spec}'. Expected one of "
        f"{sorted(PRESETS)} or 'rule:topN'."
    )


def resolve_rule_portfolio(spec: str, as_of, config: dict | None = None) -> list[str]:
    """Resolve a ``"rule:..."`` portfolio spec to a list of security IDs."""
    merged = dict(config or {})
    merged.update(parse_rule_spec(spec))
    return resolve_universe(as_of, merged)
