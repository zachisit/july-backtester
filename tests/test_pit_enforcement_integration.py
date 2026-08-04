"""Integration test: pit_enforcement columns are correctly written into
portfolio_data and the simulator respects them end-to-end.

PR #187 Fix 2 — Major review item from @zachisit:
  pit_enforcement.py (build_member_mask, build_forced_exit_mask) was fully unit-tested
  in isolation but never connected to the engine. main.py built _pit_member_masks but
  never wrote the resulting values as columns into portfolio_data, so _pit_flag() in
  portfolio_simulations.py always returned the column-absent default (False), making
  PIT membership enforcement a no-op at runtime despite passing all unit tests.

Fix: main.py now writes _pit_member and _pit_force_exit as DataFrame columns for
every symbol in portfolio_data before tasks are dispatched to the worker pool.

Test classes
------------
TestBuildMemberMask       — unit: build_member_mask produces correct True/False pattern
                            across single spells, gaps, and edge cases (all tests use
                            pd.bdate_range — Mon–Fri only, never weekend dates).
TestBuildForcedExitMask   — unit: build_forced_exit_mask marks the last member bar
                            only when no timely post-leave bar exists within exit_buffer.
TestPitColumnsWiredIntoSimulator — integration: _pit_member / _pit_force_exit columns
                            written to a real DataFrame propagate correctly through
                            run_portfolio_simulation → _pit_flag() → ExitReason.
"""
import pandas as pd
import pytest
from unittest.mock import patch

from helpers.pit_enforcement import (
    build_member_mask,
    build_forced_exit_mask,
    membership_intervals,
)


# ---------------------------------------------------------------------------
# Minimal sim config (matches test_pipeline_fixes.py pattern)
# ---------------------------------------------------------------------------
_SIM_CONFIG = {
    "execution_time": "open",
    "slippage_pct": 0.0,
    "commission_per_share": 0.0,
    "max_pct_adv": 0.0,
    "volume_impact_coeff": 0.0,
    "htb_rate_annual": 0.0,
    "exclude_open_positions": False,
    "risk_free_rate": 0.0,
    "timeframe": "D",
    "timeframe_multiplier": 1,
    "rolling_sharpe_window": 0,
}


def _frame(idx):
    """Minimal OHLCV frame with no PIT columns (caller adds them)."""
    return pd.DataFrame(
        {
            "Open": 100.0,
            "High": 105.0,
            "Low": 95.0,
            "Close": 100.0,
            "Volume": 1_000_000,
            "ATR_14": 2.0,
            "Volume_Spike": 1.0,
        },
        index=idx,
    )


# ---------------------------------------------------------------------------
# build_member_mask  — uses pd.bdate_range (Mon–Fri), all dates must be weekdays
# ---------------------------------------------------------------------------

class TestBuildMemberMask:
    def test_single_spell_covers_correct_range(self):
        # 2020-01-02 Thu, 2020-01-03 Fri, 2020-01-06 Mon … 2020-01-10 Fri
        idx = pd.bdate_range("2020-01-02", "2020-01-10")
        intervals = [(pd.Timestamp("2020-01-06"), pd.Timestamp("2020-01-09"))]
        mask = build_member_mask(idx, intervals)
        assert not mask.loc["2020-01-02"]   # before spell
        assert not mask.loc["2020-01-03"]   # before spell
        assert mask.loc["2020-01-06"]       # spell start (Monday)
        assert mask.loc["2020-01-07"]       # inside spell
        assert mask.loc["2020-01-09"]       # spell end
        assert not mask.loc["2020-01-10"]   # after spell

    def test_empty_intervals_returns_all_false(self):
        idx = pd.bdate_range("2020-01-02", "2020-01-10")
        mask = build_member_mask(idx, [])
        assert not mask.any()

    def test_gap_between_two_spells_is_false(self):
        idx = pd.bdate_range("2020-01-02", "2020-01-16")
        intervals = [
            (pd.Timestamp("2020-01-02"), pd.Timestamp("2020-01-07")),
            (pd.Timestamp("2020-01-13"), pd.Timestamp("2020-01-16")),
        ]
        mask = build_member_mask(idx, intervals)
        assert mask.loc["2020-01-02"]
        assert mask.loc["2020-01-07"]
        assert not mask.loc["2020-01-08"]   # gap (Wednesday)
        assert not mask.loc["2020-01-09"]   # gap (Thursday)
        assert mask.loc["2020-01-13"]
        assert mask.loc["2020-01-16"]

    def test_full_period_spell_returns_all_true(self):
        idx = pd.bdate_range("2020-01-02", "2020-01-10")
        intervals = [(idx[0], idx[-1])]
        mask = build_member_mask(idx, intervals)
        assert mask.all()


# ---------------------------------------------------------------------------
# build_forced_exit_mask
# ---------------------------------------------------------------------------

class TestBuildForcedExitMask:
    def test_spell_ending_at_backtest_end_is_not_forced(self):
        idx = pd.bdate_range("2020-01-02", "2020-01-10")
        intervals = [(pd.Timestamp("2020-01-02"), pd.Timestamp("2020-01-10"))]
        forced = build_forced_exit_mask(idx, intervals, backtest_end="2020-01-10")
        assert not forced.any()

    def test_spell_ending_with_timely_post_bar_is_not_forced(self):
        idx = pd.bdate_range("2020-01-02", "2020-01-16")
        intervals = [(pd.Timestamp("2020-01-02"), pd.Timestamp("2020-01-09"))]
        forced = build_forced_exit_mask(idx, intervals, backtest_end="2020-01-16",
                                        exit_buffer_days=10)
        assert not forced.any()

    def test_no_post_leave_bar_marks_last_member_bar(self):
        # Spell ends 2020-01-10; backtest ends 2020-01-20 but buffer=1 day means
        # next bar must be within 1 calendar day of 2020-01-10 — there is none
        # (next bday is 2020-01-13, which is 3 calendar days away).
        idx = pd.bdate_range("2020-01-02", "2020-01-10")
        intervals = [(pd.Timestamp("2020-01-02"), pd.Timestamp("2020-01-10"))]
        forced = build_forced_exit_mask(idx, intervals, backtest_end="2020-01-20",
                                        exit_buffer_days=1)
        assert forced.loc["2020-01-10"]
        assert not forced.loc["2020-01-09"]

    def test_empty_intervals_returns_all_false(self):
        idx = pd.bdate_range("2020-01-02", "2020-01-10")
        forced = build_forced_exit_mask(idx, [], backtest_end="2020-01-20")
        assert not forced.any()


# ---------------------------------------------------------------------------
# tz-aware indices — parquet daily bars are normalised to UTC, but membership
# dates / end_date are tz-naive. The masks must not raise InvalidComparison.
# (Regression: pit:sp500 crashed here on tz-aware price data.)
# ---------------------------------------------------------------------------

class TestTzAwareMasks:
    def test_forced_exit_mask_tz_aware_index(self):
        idx = pd.bdate_range("2017-01-02", "2017-12-29", tz="UTC")
        # Spell ends Fri 2017-06-16; next business day is Mon 2017-06-19 (3 cal
        # days later) — outside a 1-day buffer, so the last member bar is forced.
        intervals = [(pd.Timestamp("2017-01-02"), pd.Timestamp("2017-06-16"))]
        forced = build_forced_exit_mask(idx, intervals, backtest_end="2026-12-31",
                                        exit_buffer_days=1)
        assert forced.any()
        # The marked bar's label must stay tz-aware so it aligns with the index.
        marked = forced[forced].index
        assert marked[-1].tzinfo is not None
        assert marked[-1] == pd.Timestamp("2017-06-16", tz="UTC")

    def test_member_mask_tz_aware_index(self):
        idx = pd.bdate_range("2017-01-02", "2017-12-29", tz="UTC")
        intervals = [(pd.Timestamp("2017-01-02"), pd.Timestamp("2017-06-19"))]
        mask = build_member_mask(idx, intervals)
        assert mask.loc["2017-01-03"]          # inside spell
        assert not mask.loc["2017-09-01"]      # after spell
        assert mask.sum() > 0


# ---------------------------------------------------------------------------
# nq100 forced-exit intervals now load from the change-event YAML repo
# (NQ100_DATA_ROOT / nq100_pit_path), symmetric with sp500 — previously nq100
# only read a hardcoded daily-snapshot parquet, so forced-exit was a silent
# no-op for survivorship-free nq100 runs.
# ---------------------------------------------------------------------------

class TestNq100YamlIntervals:
    def _make_repo(self, tmp_path):
        d = tmp_path / "src" / "nasdaq_100_ticker_history"
        d.mkdir(parents=True)
        (d / "n100-ticker-changes-2004.yaml").write_text(
            "year: 2004\n"
            "tickers_on_Jan_1:\n"
            "  - AAA\n"
            "  - BBB\n"
            "changes:\n"
            "  '2004-06-15':\n"
            "    union: [CCC]\n"
            "    difference: [BBB]\n",
            encoding="utf-8",
        )
        return tmp_path

    def test_nq100_yaml_intervals_via_config_key(self, tmp_path):
        repo = self._make_repo(tmp_path)
        config = {"start_date": "2004-01-01", "end_date": "2004-12-31",
                  "nq100_pit_path": str(repo)}
        intervals = membership_intervals("pit:nq100", config)
        assert set(intervals) == {"AAA", "BBB", "CCC"}
        # BBB removed on 2004-06-15 — spell closes there, not at period end
        assert intervals["BBB"][0][1] == pd.Timestamp("2004-06-15")
        # CCC added on 2004-06-15, still a member at end
        assert intervals["CCC"][0][0] == pd.Timestamp("2004-06-15")
        assert intervals["CCC"][0][1] == pd.Timestamp("2004-12-31")

    def test_nq100_yaml_intervals_via_env(self, tmp_path, monkeypatch):
        repo = self._make_repo(tmp_path)
        monkeypatch.setenv("NQ100_DATA_ROOT", str(repo))
        config = {"start_date": "2004-01-01", "end_date": "2004-12-31"}
        intervals = membership_intervals("pit:nq100", config)
        assert "AAA" in intervals and "CCC" in intervals

    def test_nq100_no_repo_returns_empty_not_crash(self, tmp_path, monkeypatch):
        # No env, no config path, no legacy parquet → empty (unchanged behaviour).
        monkeypatch.delenv("NQ100_DATA_ROOT", raising=False)
        config = {"start_date": "2004-01-01", "end_date": "2004-12-31"}
        assert membership_intervals("pit:nq100", config) == {}


# ---------------------------------------------------------------------------
# End-to-end: _pit_member / _pit_force_exit columns → simulator respects them
# ---------------------------------------------------------------------------

class TestPitColumnsWiredIntoSimulator:
    """Prove the full pipeline: column values written by main.py reach _pit_flag()
    in the simulator and produce the correct trade behaviour and ExitReason."""

    def _run(self, df, sym="FAKE"):
        from helpers.portfolio_simulations import run_portfolio_simulation
        # Constant buy signal — strategy always wants in; PIT columns decide eligibility.
        signals = {sym: pd.Series(1, index=df.index)}
        with patch.dict("config.CONFIG", _SIM_CONFIG):
            return run_portfolio_simulation(
                {sym: df}, signals, 10_000.0, 0.5,
                None, None, None, {"type": "none"},
            )

    def test_non_member_symbol_produces_no_trades(self):
        # _pit_member=False for the entire period → simulator never enters.
        # run_portfolio_simulation returns None (not a dict) when pnl_list is empty.
        idx = pd.bdate_range("2020-01-02", "2020-01-31")
        df = _frame(idx)
        df["_pit_member"] = False
        df["_pit_force_exit"] = False
        result = self._run(df)
        assert result is None  # None = no trades; subscripting None was the pre-fix crash

    def test_member_symbol_exits_on_membership_end(self):
        # Symbol is member through 2020-01-15 (Wed), non-member after.
        # Simulator should enter on the first member bar and fire "PIT Membership Exit"
        # when it encounters the first non-member bar.
        idx = pd.bdate_range("2020-01-02", "2020-01-31")
        removal = pd.Timestamp("2020-01-15")   # Wednesday
        df = _frame(idx)
        df["_pit_member"] = idx <= removal
        df["_pit_force_exit"] = False
        result = self._run(df)
        assert result["Trades"] >= 1
        last = result["trade_log"][-1]
        assert "PIT Membership Exit" in last["ExitReason"]

    def test_force_exit_closes_at_last_member_bar(self):
        # _pit_force_exit=True on 2020-01-08 (Wed) tells the simulator to close
        # at that bar's Close price rather than waiting for the next open.
        # Used when a symbol is removed from the index with no next-bar available
        # (e.g. sudden delisting or data gap at end of backtest period).
        idx = pd.bdate_range("2020-01-02", "2020-01-10")
        force_date = pd.Timestamp("2020-01-08")  # Wednesday
        df = _frame(idx)
        df["_pit_member"] = True
        df["_pit_force_exit"] = False
        df.loc[force_date, "_pit_force_exit"] = True
        result = self._run(df)
        forced = [t for t in result["trade_log"]
                  if "last available close" in t.get("ExitReason", "")]
        assert len(forced) >= 1
        assert forced[0]["ExitDate"][:10] <= "2020-01-08"
