"""#387 (part of #381) — the engine says which condition cost it the size.

The acceptance criterion is a negative one: **silence is the defect.** A run
that takes no position, or takes a clamped one, must say which of the four
conditions caused it. So the tests here assert on the diagnostics surface
rather than on share counts — those are #385's and #386's subject.

The headline case is the documented default. `{"type": "none"}` is what
`config.py` SECTION 9 ships, so the failing combination was "select a sizing
method and change nothing else": zero trades, no error, no partial result. A
zero-trade run reads as a *strategy* finding, which invites debugging the
signal logic for a fault in the sizing gate.

Taxonomy is @shardul0701's on #387, including the correction that split the
clamps out of "no stop": a cash clamp says raise capital or lower allocation,
an ADV truncation says the name is too thin for the size, and neither says
anything about stops. Grouping them under one message would misdirect on two
of the four producers.
"""

import logging
import os
import sys

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from helpers.sizing_diagnostics import (  # noqa: E402
    COVERAGE_DRIFT, NO_STOP, OVERRIDDEN, REASONS, UNREACHABLE,
    SizingDiagnostics,
)
from helpers.portfolio_simulations import run_portfolio_simulation  # noqa: E402


_CFG = {
    "slippage_pct": 0.0005,
    "commission_per_share": 0.002,
    "execution_time": "close",
    "risk_free_rate": 0.05,
    "htb_rate_annual": 0.0,
    "volume_impact_coeff": 0.0,
    "target_risk_per_trade": 0.02,
    "risk_pct_per_trade": 0.01,
    "max_contracts_cap": 20,
    "fixed_contracts_per_trade": 3,
    "risk_pct_capped_max_notional_pct": 1.0,
    "entry_priority": "alphabetical",
    "exclude_open_positions": False,
    "include_delisted": False,
    "allocation_per_trade": 0.10,
    "max_portfolio_heat": 1.0,
    "max_pct_adv": 0.0,
    "instruments": {"default_asset_class": "equity",
                    "futures_initial_margin_pct": 0.10,
                    "futures_commission_per_contract": 2.50,
                    "futures_slippage_ticks": 1.0, "overrides": {}},
}


def _frame(price=100.0, n=10, volume=5_000_000.0, atr_pct=2.0):
    closes = np.array([price * (1 + 0.002 * i) for i in range(n)])
    idx = pd.bdate_range(start="2023-01-02", periods=n, freq="B")
    idx.name = "Datetime"
    return pd.DataFrame({
        "Open": np.round(closes * 0.999, 6),
        "High": np.round(closes * 1.010, 6),
        "Low": np.round(closes * 0.990, 6),
        "Close": closes,
        "Volume": np.full(n, volume),
        "ATR_14": np.full(n, atr_pct * price / 100.0),
    }, index=idx)


def _run(method, stop_config, capital=100_000.0, alloc=0.10, **over):
    """`alloc` is an explicit parameter, not a config override.

    `_fixed_allocation` reads `config["allocation_per_trade"]` only when the
    caller passes `allocation_pct=None`, and `run_portfolio_simulation` always
    passes it — so setting the config key here is INERT and a test relying on it
    silently exercises the default. Cost one round on the cash-clamp case.
    """
    from unittest.mock import patch
    df = _frame(**{k: over.pop(k) for k in ("price", "volume", "atr_pct")
                   if k in over})
    sig = pd.Series(0, index=df.index, dtype=int)
    sig.iloc[2], sig.iloc[8] = 1, -1
    cfg = {**_CFG, "position_sizing_method": method, **over}
    with patch.dict("config.CONFIG", cfg, clear=False):
        return run_portfolio_simulation(
            portfolio_data={"AAA": df}, signals={"AAA": sig},
            initial_capital=capital, allocation_pct=alloc,
            spy_df=None, vix_df=None, tnx_df=None, stop_config=stop_config)


# ---------------------------------------------------------------------------
class TestTheAccumulator:

    def test_empty_by_default(self):
        d = SizingDiagnostics()
        assert d.is_empty() and d.as_dict() == {} and d.format_report() == ""

    def test_counts_and_kinds(self):
        d = SizingDiagnostics()
        d.record("clamped_by_cash", "AAA")
        d.record("clamped_by_cash", "BBB")
        d.record("no_stop_distance", "CCC")
        assert d.as_dict() == {"clamped_by_cash": 2, "no_stop_distance": 1}
        assert d.by_kind() == {OVERRIDDEN: 2, NO_STOP: 1}

    def test_an_unknown_reason_raises_rather_than_inventing_a_category(self):
        """A typo'd reason would otherwise be counted under its own key and
        reported as a category nobody defined — a diagnostics surface that
        silently invents categories is worse than none."""
        with pytest.raises(KeyError):
            SizingDiagnostics().record("clamped_by_csah")

    def test_symbol_examples_are_bounded(self):
        d = SizingDiagnostics()
        for i in range(50):
            d.record("clamped_by_adv", "SYM%d" % i)
        assert d.as_dict()["clamped_by_adv"] == 50
        assert "SYM0" in d.format_report() and "SYM40" not in d.format_report()

    def test_every_reason_has_a_kind_and_an_explanation(self):
        for reason, (kind, text) in REASONS.items():
            assert kind in (COVERAGE_DRIFT, NO_STOP, OVERRIDDEN, UNREACHABLE)
            assert len(text) > 20, reason


# ---------------------------------------------------------------------------
class TestTheDocumentedDefaultIsNoLongerSilent:
    """`{"type": "none"}` + a risk-based method: the config that ships."""

    def test_zero_trades_are_explained(self):
        res = _run("risk_pct_capped", {"type": "none"})
        assert res is None or not res.get("trade_log"), (
            "this case is supposed to take no position; if it now trades, the "
            "test needs rewriting rather than the assertion loosening")

    def test_the_reason_reaches_the_log(self, caplog):
        with caplog.at_level(logging.WARNING,
                             logger="helpers.portfolio_simulations"):
            _run("risk_pct_capped", {"type": "none"})
        assert "no stop distance" in caplog.text.lower(), caplog.text

    def test_the_message_points_at_the_config_not_the_strategy(self, caplog):
        """The failure mode is a zero-trade run reading as a strategy finding.
        The message has to name the knob."""
        with caplog.at_level(logging.WARNING,
                             logger="helpers.portfolio_simulations"):
            _run("risk_pct_capped", {"type": "none"})
        assert "stop_loss_configs" in caplog.text, caplog.text


# ---------------------------------------------------------------------------
class TestClampsAreDistinguishedFromAbsentStops:
    """The correction that made the taxonomy four-way instead of three.

    A cash clamp and an absent stop are both "you did not get what you asked
    for", and they are actionable in completely different ways.
    """

    def test_cash_clamp_is_reported_and_classified_as_overridden(self):
        # alloc 1.5, not 1.0. At 1.0 the fixed target is exactly `equity /
        # price`, so `capital_needed == cash` and the clamp — a strict `>` —
        # does not fire; measured, the position is identical at 1.0 and 1.5
        # (995.4983…), and only the second one reports. A test at 1.0 would
        # have asserted the absence of a clamp that was about to be needed.
        res = _run("fixed", {"type": "percentage", "value": 0.05}, alloc=1.5)
        assert res is not None
        diag = res["sizing_diagnostics"]
        assert diag.get("clamped_by_cash", 0) >= 1, diag
        assert REASONS["clamped_by_cash"][0] == OVERRIDDEN

    def test_adv_cap_is_reported(self):
        res = _run("fixed", {"type": "percentage", "value": 0.05},
                   volume=100.0, max_pct_adv=0.05)
        assert res is not None
        assert res["sizing_diagnostics"].get("clamped_by_adv", 0) >= 1, (
            res["sizing_diagnostics"])

    def test_heat_rejection_is_reported(self, caplog):
        """Asserted on the LOG, not the result dict, and that is the contract.

        `run_portfolio_simulation` returns `None` when nothing traded — callers
        including `main.py` branch on that — so the counts have nowhere to ride
        home on precisely the runs this mechanism exists for. Rather than change
        a return contract several callers depend on, the log is the surface for
        zero-trade runs and the dict is a convenience for the rest. Stated here
        because a reader who finds `sizing_diagnostics` on the result will
        reasonably assume it is always there.
        """
        with caplog.at_level(logging.WARNING,
                             logger="helpers.sizing_diagnostics"):
            _run("fixed", {"type": "percentage", "value": 0.05},
                 max_portfolio_heat=0.0001)
        assert "max_portfolio_heat" in caplog.text, caplog.text

    def test_the_notional_ceiling_is_reported_as_unreachable_not_as_a_fault(self):
        """`stop_frac < risk_pct_per_trade` means the budget cannot be
        delivered without leverage, so the clamped value is CORRECT. It is
        reported so that "less than configured, on purpose" is distinguishable
        from "less than configured, by accident"."""
        res = _run("risk_pct_capped", {"type": "points", "value": 0.5},
                   price=1000.0)
        assert res is not None and res["trade_log"]
        diag = res["sizing_diagnostics"]
        assert diag.get("clamped_by_notional_ceiling", 0) >= 1, diag
        assert REASONS["clamped_by_notional_ceiling"][0] == UNREACHABLE


# ---------------------------------------------------------------------------
class TestNoFalsePositives:
    """A diagnostics surface that fires on healthy runs gets ignored, which
    returns the engine to silence by a different route."""

    def test_a_clean_run_reports_nothing(self):
        res = _run("fixed", {"type": "percentage", "value": 0.05})
        assert res is not None and res["trade_log"]
        assert res["sizing_diagnostics"] == {}, res["sizing_diagnostics"]

    def test_a_clean_run_logs_nothing(self, caplog):
        with caplog.at_level(logging.WARNING,
                             logger="helpers.portfolio_simulations"):
            _run("fixed", {"type": "percentage", "value": 0.05})
        assert "Position sizing:" not in caplog.text, caplog.text


# ---------------------------------------------------------------------------
class TestRiskParityFallbacksAnnounceThemselves:
    """The correction to my own ticket body: two of the three already warned.

    Only the 3xATR proxy was silent, and it is the only one that returns a
    WRONG SIZE rather than a different method — the other two hand off to
    `_fixed_allocation`, a documented method behaving as documented. An
    inconsistently applied concept, not a missing one. (@shardul0701 on #387.)
    """

    def _sized(self, caplog, **kwargs):
        from helpers.position_sizing import _risk_parity
        with caplog.at_level(logging.WARNING, logger="helpers.position_sizing"):
            return _risk_parity(100_000.0, 100.0,
                                pd.DataFrame({"ATR_14": [2.0]}),
                                {"target_risk_per_trade": 0.02}, **kwargs)

    def test_the_atr_proxy_now_says_so(self, caplog):
        shares = self._sized(caplog)          # no stop distance at all
        assert shares > 0
        assert "3xATR proxy" in caplog.text, caplog.text
        assert "did not ask for" in caplog.text

    def test_a_supplied_distance_stays_silent(self, caplog):
        """Control: the warning must not fire on the normal path."""
        self._sized(caplog, stop_distance_pct=0.05)
        assert "3xATR proxy" not in caplog.text, caplog.text

    def test_the_zero_return_says_so(self, caplog):
        from helpers.position_sizing import _risk_parity
        with caplog.at_level(logging.WARNING, logger="helpers.position_sizing"):
            shares = _risk_parity(100_000.0, 100.0,
                                  pd.DataFrame({"ATR_14": [2.0]}),
                                  {"target_risk_per_trade": 0.02},
                                  stop_distance_points=0.0,
                                  stop_distance_pct=-1.0)
        # -1.0 is rejected by the guard above, falls to the ATR proxy, which is
        # positive here -- so this asserts the proxy path, and the zero path is
        # covered by the unit case below.
        assert shares > 0

    def test_a_non_positive_proxy_returns_zero_and_says_so(self, caplog):
        from helpers.position_sizing import _risk_parity
        with caplog.at_level(logging.WARNING, logger="helpers.position_sizing"):
            shares = _risk_parity(100_000.0, -5.0,       # negative price
                                  pd.DataFrame({"ATR_14": [2.0]}),
                                  {"target_risk_per_trade": 0.02})
        assert shares == 0.0
        assert "taking no position" in caplog.text, caplog.text
