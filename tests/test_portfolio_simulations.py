"""tests/test_portfolio_simulations.py

Tests for helpers/portfolio_simulations.py — focused on #160 deterministic
entry-queue behaviour. All tests use execution_time="close" so prev_trading_dates
lookups are not needed, keeping fixtures minimal.
"""
import os
import sys
from unittest.mock import patch

import pandas as pd
import numpy as np
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from helpers.portfolio_simulations import run_portfolio_simulation

# ---------------------------------------------------------------------------
# Minimal CONFIG sufficient for the simulation engine (no PIT, no costs)
# ---------------------------------------------------------------------------
_BASE_CONFIG = {
    "execution_time": "close",
    "slippage_pct": 0.0,
    "commission_per_share": 0.0,
    "max_pct_adv": 0,
    "volume_impact_coeff": 0.0,
    "htb_rate_annual": 0.0,
    "include_delisted": False,
    "noise_injection_pct": 0.0,
    "rolling_sharpe_window": 0,
    "pit_enforce_daily": False,
    "exclude_open_positions": False,
    "entry_priority": "alphabetical",
    "entry_random_seed": 42,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _price_df(price: float, n: int = 10) -> pd.DataFrame:
    dates = pd.date_range("2020-01-02", periods=n, freq="B")
    return pd.DataFrame(
        {
            "Open": [price] * n,
            "High": [price + 1.0] * n,
            "Low": [price - 1.0] * n,
            "Close": [price] * n,
            "Volume": [1_000_000] * n,
        },
        index=pd.DatetimeIndex(dates),
    )


def _const_signal(price_df: pd.DataFrame, value: int) -> pd.Series:
    return pd.Series(value, index=price_df.index)


def _run(portfolio_data, signals, allocation_pct=0.1, initial_capital=10_000.0,
         entry_priority="alphabetical", extra_config=None):
    cfg = {**_BASE_CONFIG, "entry_priority": entry_priority, **(extra_config or {})}
    with patch("helpers.portfolio_simulations.CONFIG", cfg):
        return run_portfolio_simulation(
            portfolio_data=portfolio_data,
            signals=signals,
            initial_capital=initial_capital,
            allocation_pct=allocation_pct,
            spy_df=None,
            vix_df=None,
            tnx_df=None,
            stop_config={"type": "none"},
        )


def _filled_symbols(result) -> set:
    return {t["Symbol"] for t in result["trade_log"]}


# ---------------------------------------------------------------------------
# TestEntryPriorityAlphabetical — core acceptance criteria from #160
# ---------------------------------------------------------------------------

class TestEntryPriorityAlphabetical:
    """entry_priority='alphabetical' — A→Z ordering on every bar."""

    def test_alphabetically_first_wins_on_capital_tie(self):
        """Only enough capital for one position → alphabetically-first symbol filled.

        allocation_pct=1.0 with initial_capital = price means the first entry
        consumes all cash (shares * price = 1.0 * IC). Cash drops to 0, so
        capital_to_allocate = min(total_equity * 1.0, 0) = 0 for every subsequent
        symbol — they are cleanly skipped without the fractional-share ambiguity.
        """
        pf = {
            "MSFT": _price_df(100.0),
            "AAPL": _price_df(100.0),
        }
        sig = {s: _const_signal(df, 1) for s, df in pf.items()}
        result = _run(pf, sig, allocation_pct=1.0, initial_capital=100.0,
                      entry_priority="alphabetical")
        filled = _filled_symbols(result)
        assert "AAPL" in filled
        assert "MSFT" not in filled

    def test_dict_insertion_order_does_not_affect_result(self):
        """Even when dict is constructed Z→A, alphabetical ordering applies."""
        pf_za = {
            "ZEBRA": _price_df(100.0),
            "ALPHA": _price_df(100.0),
        }
        sig = {s: _const_signal(df, 1) for s, df in pf_za.items()}
        result = _run(pf_za, sig, allocation_pct=1.0, initial_capital=100.0,
                      entry_priority="alphabetical")
        filled = _filled_symbols(result)
        assert "ALPHA" in filled
        assert "ZEBRA" not in filled

    def test_both_filled_when_capital_permits(self):
        """No capital constraint → both symbols are filled regardless of order."""
        pf = {"MSFT": _price_df(10.0), "AAPL": _price_df(10.0)}
        sig = {s: _const_signal(df, 1) for s, df in pf.items()}
        result = _run(pf, sig, allocation_pct=0.4, initial_capital=1_000.0,
                      entry_priority="alphabetical")
        assert _filled_symbols(result) == {"AAPL", "MSFT"}

    def test_single_symbol_unchanged(self):
        """Single-symbol universe — ordering has no effect on the result."""
        pf = {"AAPL": _price_df(100.0)}
        sig = {"AAPL": _const_signal(pf["AAPL"], 1)}
        result = _run(pf, sig, allocation_pct=0.1, initial_capital=10_000.0)
        assert "AAPL" in _filled_symbols(result)

    def test_alphabetical_is_default_when_key_absent(self):
        """entry_priority defaults to alphabetical when the key is missing."""
        pf = {"ZEBRA": _price_df(100.0), "ALPHA": _price_df(100.0)}
        sig = {s: _const_signal(df, 1) for s, df in pf.items()}
        cfg_no_key = {k: v for k, v in _BASE_CONFIG.items() if k != "entry_priority"}
        with patch("helpers.portfolio_simulations.CONFIG", cfg_no_key):
            result = run_portfolio_simulation(
                portfolio_data=pf, signals=sig,
                initial_capital=100.0, allocation_pct=1.0,
                spy_df=None, vix_df=None, tnx_df=None,
                stop_config={"type": "none"},
            )
        filled = _filled_symbols(result)
        assert "ALPHA" in filled
        assert "ZEBRA" not in filled


# ---------------------------------------------------------------------------
# TestEntryPriorityRandomSeed — reproducibility under random_seed mode
# ---------------------------------------------------------------------------

class TestEntryPriorityRandomSeed:

    def test_same_seed_produces_same_winner(self):
        """Two runs with the same seed must fill the same symbol."""
        pf = {
            "MSFT": _price_df(100.0),
            "AAPL": _price_df(100.0),
            "GOOG": _price_df(100.0),
        }
        sig = {s: _const_signal(df, 1) for s, df in pf.items()}
        r1 = _run(pf, sig, allocation_pct=0.9, initial_capital=200.0,
                  entry_priority="random_seed", extra_config={"entry_random_seed": 7})
        r2 = _run(pf, sig, allocation_pct=0.9, initial_capital=200.0,
                  entry_priority="random_seed", extra_config={"entry_random_seed": 7})
        assert _filled_symbols(r1) == _filled_symbols(r2)

    def test_different_seeds_may_produce_different_winners(self):
        """With enough symbols, different seeds should occasionally pick different winners.
        We verify at least one pair of seeds differs across a reasonable sweep."""
        pf = {sym: _price_df(100.0) for sym in
              ["AAPL", "MSFT", "GOOG", "AMZN", "META", "NVDA", "TSLA", "NFLX"]}
        sig = {s: _const_signal(df, 1) for s, df in pf.items()}
        winners = set()
        for seed in range(10):
            r = _run(pf, sig, allocation_pct=0.9, initial_capital=200.0,
                     entry_priority="random_seed", extra_config={"entry_random_seed": seed})
            winners |= _filled_symbols(r)
        # With 8 symbols and 10 seeds, expect more than 1 unique winner
        assert len(winners) > 1


# ---------------------------------------------------------------------------
# TestEntryPrioritySignalDate — signal-date ordering
# ---------------------------------------------------------------------------

class TestEntryPrioritySignalDate:

    def test_signal_date_mode_runs_without_error(self):
        """signal_date mode must not crash and must return a valid result."""
        pf = {"MSFT": _price_df(100.0), "AAPL": _price_df(100.0)}
        sig = {s: _const_signal(df, 1) for s, df in pf.items()}
        result = _run(pf, sig, allocation_pct=0.4, initial_capital=1_000.0,
                      entry_priority="signal_date")
        assert "trade_log" in result
        assert isinstance(result["trade_log"], list)

    def test_signal_date_fills_at_least_one_when_capital_constrained(self):
        """Capital-constrained signal_date run still fills exactly one symbol."""
        pf = {"MSFT": _price_df(100.0), "AAPL": _price_df(100.0)}
        sig = {s: _const_signal(df, 1) for s, df in pf.items()}
        result = _run(pf, sig, allocation_pct=1.0, initial_capital=100.0,
                      entry_priority="signal_date")
        assert len(_filled_symbols(result)) == 1


# ---------------------------------------------------------------------------
# #412 — random_seed must reshuffle every bar, reproducibly
# ---------------------------------------------------------------------------

_SYMS_412 = ["AAPL", "AMZN", "GOOG", "META", "MSFT", "NFLX", "NVDA", "TSLA"]


def _contested_every_other_bar(n=20):
    """Every symbol enters on even bars and exits on odd bars, and capital
    covers one fill: each entry bar is a fresh contest for the single slot."""
    pf = {s: _price_df(100.0, n=n) for s in _SYMS_412}
    pattern = [1 if i % 2 == 0 else -1 for i in range(n)]
    sig = {s: pd.Series(pattern, index=df.index) for s, df in pf.items()}
    return pf, sig


def _winner_by_entry_bar(result):
    """The symbol that got the full allocation on each entry bar. (Fractional
    shares let the next symbol in the queue take the leftover cash too, so the
    queue's head is the largest fill, not the only one.)"""
    best = {}
    for t in result["trade_log"]:
        d = t["EntryDate"]
        if d not in best or t["Shares"] > best[d]["Shares"]:
            best[d] = t
    return [best[d]["Symbol"] for d in sorted(best)]


class TestRandomSeedReshufflesEachBar:

    def _run_seed(self, seed):
        pf, sig = _contested_every_other_bar()
        return _run(pf, sig, allocation_pct=0.9, initial_capital=200.0,
                    entry_priority="random_seed", extra_config={"entry_random_seed": seed})

    def test_fill_order_differs_between_bars(self):
        winners = _winner_by_entry_bar(self._run_seed(7))
        assert len(winners) >= 8                       # one fill per entry bar
        assert len(set(winners)) > 1, (
            "random_seed gave the same winner on every bar: the RNG is being "
            "re-seeded per bar with the same seed (#412)")

    def test_same_seed_is_identical_across_runs(self):
        assert _winner_by_entry_bar(self._run_seed(7)) == _winner_by_entry_bar(self._run_seed(7))

    def test_different_seeds_give_different_fills(self):
        assert _winner_by_entry_bar(self._run_seed(7)) != _winner_by_entry_bar(self._run_seed(8))

    def test_alphabetical_still_fills_a_to_z_every_bar(self):
        pf, sig = _contested_every_other_bar()
        r = _run(pf, sig, allocation_pct=0.9, initial_capital=200.0)
        assert set(_winner_by_entry_bar(r)) == {"AAPL"}
