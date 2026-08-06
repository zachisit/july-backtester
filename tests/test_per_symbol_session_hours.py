"""
Tests for per-symbol trading-session length (issue #270).

`trading_hours_per_day` is a single process-wide number, but instruments
already resolve per symbol (`resolve_instrument` branches per symbol on
margin mode, integer units, borrow, calendar). A book mixing equities
(6.5h RTH) with 24h futures therefore gets the wrong bars-per-day for one
side of it no matter what the global is set to -- and that feeds straight
into the 20-day ADV window (#264/#268).

The overriding constraint is that **no existing configuration may change
behaviour**, so the calendar-derived hours are opt-in. These tests pin both
halves: the new mechanism works, and the default path is untouched.

No network, no randomness.
"""

import os
import sys
from unittest.mock import patch

import pandas as pd
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from helpers.instruments import (  # noqa: E402
    CALENDAR_SESSION_HOURS,
    CME_ETH,
    DEFAULT_SESSION_HOURS,
    NYSE,
    resolve_instrument,
    resolve_session_hours,
)
from helpers.portfolio_simulations import run_portfolio_simulation  # noqa: E402
from helpers.timeframe_utils import get_bars_per_day_exact  # noqa: E402


class TestResolveSessionHoursPrecedence:
    """1. per-symbol override -> 2. calendar opt-in -> 3. global -> 4. default."""

    def test_defaults_to_the_documented_six_and_a_half(self):
        assert resolve_session_hours("AAPL", {}) == DEFAULT_SESSION_HOURS

    def test_global_is_honoured_when_no_override(self):
        cfg = {"trading_hours_per_day": 24}
        assert resolve_session_hours("AAPL", cfg) == 24.0

    def test_per_symbol_override_wins_over_global(self):
        cfg = {
            "trading_hours_per_day": 6.5,
            "instruments": {"overrides": {"ESM6": {"session_hours": 23}}},
        }
        assert resolve_session_hours("ESM6", cfg) == 23.0
        assert resolve_session_hours("AAPL", cfg) == 6.5

    def test_calendar_opt_in_derives_per_symbol(self):
        cfg = {"instruments": {"session_hours_from_calendar": True}}
        assert resolve_session_hours("AAPL", cfg) == CALENDAR_SESSION_HOURS[NYSE]
        assert resolve_session_hours("ESM6", cfg) == CALENDAR_SESSION_HOURS[CME_ETH]

    def test_calendar_opt_in_is_off_by_default(self):
        """Without the flag a futures symbol still gets the global -- the
        whole point of keeping existing runs byte-identical."""
        cfg = {"trading_hours_per_day": 6.5}
        assert resolve_session_hours("ESM6", cfg) == 6.5

    def test_override_beats_the_calendar_opt_in(self):
        cfg = {
            "instruments": {
                "session_hours_from_calendar": True,
                "overrides": {"ESM6": {"session_hours": 22}},
            }
        }
        assert resolve_session_hours("ESM6", cfg) == 22.0

    def test_unknown_calendar_falls_back_to_the_global(self):
        cfg = {
            "trading_hours_per_day": 8,
            "instruments": {
                "session_hours_from_calendar": True,
                "overrides": {"WEIRD": {"calendar": "LSE"}},
            },
        }
        assert resolve_session_hours("WEIRD", cfg) == 8.0

    @pytest.mark.parametrize("bad", [0, -1, -6.5])
    def test_rejects_non_positive_session(self, bad):
        with pytest.raises(ValueError, match="must be > 0"):
            resolve_session_hours("AAPL", {"trading_hours_per_day": bad})

    def test_instrument_carries_the_override(self):
        cfg = {"instruments": {"overrides": {"ESM6": {"session_hours": 23}}}}
        assert resolve_instrument("ESM6", cfg).session_hours == 23.0

    def test_session_hours_defaults_to_none_on_the_instrument(self):
        """None means 'unset' -- config decides. A concrete default here would
        silently outrank the global."""
        assert resolve_instrument("AAPL", {}).session_hours is None
        assert resolve_instrument("ESM6", {}).session_hours is None


class TestBarsPerDayAcceptsExplicitSessionHours:

    def test_session_hours_argument_overrides_the_global(self):
        cfg = {"timeframe": "H", "timeframe_multiplier": 1,
               "trading_hours_per_day": 6.5}
        assert get_bars_per_day_exact(cfg) == pytest.approx(6.5)
        assert get_bars_per_day_exact(cfg, session_hours=23) == pytest.approx(23.0)

    def test_none_keeps_the_global(self):
        cfg = {"timeframe": "H", "trading_hours_per_day": 8}
        assert get_bars_per_day_exact(cfg, session_hours=None) == pytest.approx(8.0)

    def test_daily_ignores_session_hours_entirely(self):
        """A daily bar is one bar per day whatever the session length is."""
        cfg = {"timeframe": "D"}
        assert get_bars_per_day_exact(cfg, session_hours=23) == 1.0

    def test_rejects_non_positive_explicit_hours(self):
        with pytest.raises(ValueError, match="trading_hours_per_day"):
            get_bars_per_day_exact({"timeframe": "MIN"}, session_hours=0)


class TestSessionHoursResolutionIsLazy:
    """
    D/W/M never read a session length, so they must neither pay for resolving
    one nor be able to fail on it. Passing a callable defers resolution to the
    intraday branches only.
    """

    @pytest.mark.parametrize("timeframe", ["D", "W", "M"])
    def test_callable_is_not_invoked_for_daily_timeframes(self, timeframe):
        calls = []

        def _boom():
            calls.append(1)
            raise AssertionError("session hours resolved on a D/W/M timeframe")

        assert get_bars_per_day_exact(
            {"timeframe": timeframe}, session_hours=_boom
        ) == 1.0
        assert calls == []

    def test_callable_is_invoked_for_intraday(self):
        calls = []

        def _hours():
            calls.append(1)
            return 23.0

        result = get_bars_per_day_exact(
            {"timeframe": "H", "timeframe_multiplier": 1}, session_hours=_hours
        )
        assert result == pytest.approx(23.0)
        assert calls == [1]

    @pytest.mark.parametrize("timeframe", ["D", "W", "M"])
    def test_daily_run_survives_a_bad_global_it_never_reads(self, timeframe):
        """
        Regression: wiring per-symbol resolution in eagerly made a D run with
        trading_hours_per_day=0 raise, where it had always worked.
        """
        from helpers.instruments import resolve_session_hours as _rsh

        cfg = {"timeframe": timeframe, "trading_hours_per_day": 0}
        assert get_bars_per_day_exact(
            cfg, session_hours=lambda: _rsh("AAPL", cfg)
        ) == 1.0


# --- engine-level -----------------------------------------------------------

PRICE = 1.0
N_BARS = 200
ENTRY_IDX = 150


def _hourly_df(volume, price=PRICE, n_bars=N_BARS):
    idx = pd.DatetimeIndex(pd.date_range("2024-01-02", periods=n_bars, freq="h"))
    idx.name = "Datetime"
    return pd.DataFrame(
        {"Open": price, "High": price, "Low": price, "Close": price,
         "Volume": float(volume)},
        index=idx,
    )


def _run(portfolio_data, cfg_extra=None, entry_idx=ENTRY_IDX):
    signals = {}
    for sym, df in portfolio_data.items():
        s = pd.Series(0, index=df.index)
        s.iloc[entry_idx] = 1
        signals[sym] = s

    cfg = {
        "timeframe": "H",
        "timeframe_multiplier": 1,
        "trading_hours_per_day": 6.5,
        "execution_time": "close",
        "slippage_pct": 0.0,
        "commission_per_share": 0.0,
        "max_pct_adv": 0.05,
        "volume_impact_coeff": 0.0,
        "risk_free_rate": 0.05,
        "htb_rate_annual": 0.0,
        "position_sizing_method": "fixed",
    }
    cfg.update(cfg_extra or {})

    with patch.dict("config.CONFIG", cfg):
        return run_portfolio_simulation(
            portfolio_data=portfolio_data,
            signals=signals,
            initial_capital=10_000_000.0,  # far more than any cap allows
            allocation_pct=0.10,
            spy_df=None,
            vix_df=None,
            tnx_df=None,
            stop_config={"type": "none"},
        )


class TestEngineUsesPerSymbolSessionHours:

    def test_default_run_is_unchanged(self):
        """No override, no opt-in -> the global 6.5 for everything."""
        volume = 20_000.0
        result = _run({"AAPL": _hourly_df(volume)})
        trade = result["trade_log"][0]
        assert trade["Shares"] == pytest.approx(volume * 6.5 * 0.05, rel=1e-9)

    def test_per_symbol_override_changes_only_that_symbol(self):
        """
        The mixed-book case. AAPL keeps 6.5h; the futures symbol gets 23h, so
        its ADV -- and therefore its cap -- is 23/6.5 larger on identical
        per-bar volume.
        """
        volume = 20_000.0
        result = _run(
            {"AAPL": _hourly_df(volume), "ESM6": _hourly_df(volume)},
            cfg_extra={
                "instruments": {
                    "overrides": {
                        # keep ES on cash/fractional sizing so the assertion is
                        # about session hours, not contract rounding
                        "ESM6": {"asset_class": "equity", "session_hours": 23},
                    }
                }
            },
        )

        by_symbol = {t["Symbol"]: t for t in result["trade_log"]}
        assert by_symbol["AAPL"]["Shares"] == pytest.approx(
            volume * 6.5 * 0.05, rel=1e-9
        )
        assert by_symbol["ESM6"]["Shares"] == pytest.approx(
            volume * 23.0 * 0.05, rel=1e-9
        )
        assert by_symbol["ESM6"]["Shares"] > by_symbol["AAPL"]["Shares"]

    def test_two_symbols_do_not_share_one_session_length(self):
        """
        Regression guard for the bug this issue is about: a single global
        bars-per-day would give both symbols the same cap on identical
        volume, hiding the difference entirely.
        """
        volume = 20_000.0
        result = _run(
            {"EQ": _hourly_df(volume), "FUT": _hourly_df(volume)},
            cfg_extra={
                "instruments": {
                    "overrides": {"FUT": {"asset_class": "equity",
                                          "session_hours": 23}}
                }
            },
        )
        by_symbol = {t["Symbol"]: t for t in result["trade_log"]}
        assert by_symbol["EQ"]["Shares"] != pytest.approx(
            by_symbol["FUT"]["Shares"], rel=1e-6
        )

    def test_calendar_opt_in_works_end_to_end(self):
        volume = 20_000.0
        result = _run(
            {"AAPL": _hourly_df(volume)},
            cfg_extra={"instruments": {"session_hours_from_calendar": True}},
        )
        trade = result["trade_log"][0]
        # AAPL resolves to the NYSE calendar -> 6.5h, same as the global here.
        assert trade["Shares"] == pytest.approx(
            volume * CALENDAR_SESSION_HOURS[NYSE] * 0.05, rel=1e-9
        )

    def test_daily_run_ignores_a_bad_session_length_entirely(self):
        """
        End-to-end form of the laziness guard: a daily backtest with a
        nonsensical trading_hours_per_day must still run and still cap.
        """
        volume = 20_000.0
        idx = pd.DatetimeIndex(pd.date_range("2024-01-02", periods=60, freq="B"))
        idx.name = "Datetime"
        df = pd.DataFrame(
            {"Open": PRICE, "High": PRICE, "Low": PRICE, "Close": PRICE,
             "Volume": volume},
            index=idx,
        )
        signal = pd.Series(0, index=idx)
        signal.iloc[40] = 1

        cfg = {
            "timeframe": "D",
            "trading_hours_per_day": 0,   # nonsense, and irrelevant on D
            "execution_time": "close",
            "slippage_pct": 0.0,
            "commission_per_share": 0.0,
            "max_pct_adv": 0.05,
            "volume_impact_coeff": 0.0,
            "risk_free_rate": 0.05,
            "htb_rate_annual": 0.0,
            "position_sizing_method": "fixed",
        }
        with patch.dict("config.CONFIG", cfg):
            result = run_portfolio_simulation(
                portfolio_data={"T": df},
                signals={"T": signal},
                initial_capital=1_000_000.0,
                allocation_pct=0.10,
                spy_df=None,
                vix_df=None,
                tnx_df=None,
                stop_config={"type": "none"},
            )

        trade = result["trade_log"][0]
        assert trade["Shares"] == pytest.approx(volume * 0.05, rel=1e-9)

    def test_global_still_applies_when_nothing_is_overridden(self):
        volume = 20_000.0
        result = _run(
            {"AAPL": _hourly_df(volume)},
            cfg_extra={"trading_hours_per_day": 13},
        )
        trade = result["trade_log"][0]
        assert trade["Shares"] == pytest.approx(volume * 13.0 * 0.05, rel=1e-9)
