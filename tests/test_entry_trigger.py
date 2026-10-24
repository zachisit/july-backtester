"""Tests for ``entry_trigger`` -- edge (default since #401) vs level entry semantics.

The engine has always tested the signal *level* (``== 1`` / ``== -2``) to decide
whether a bar is an entry. A strategy that emits a forward-filled *state* series
-- 1 on every bar of a hold, which ``custom_strategies/bull_flag.py`` produces
via ``.replace(0, np.nan).ffill()`` -- therefore makes every hold bar
entry-eligible, and which bar actually gets taken becomes a function of how much
cash happens to be free.

``entry_trigger: "edge"`` restricts entry to the transition INTO the entry state,
matching how the live scanner triggers. It is the default since #401: under
"level" a hold-state signal re-enters on the bar after (or the bar of) a stop-out,
booking trades the strategy never signalled. "level" stays available per run.

Covers the two pure helpers and all four engine wiring sites (long/short entry
gate, long/short priority sort key) in helpers/portfolio_simulations.py.
"""

import pandas as pd
import pytest
from unittest.mock import patch

from helpers.config_validator import validate_config
from helpers.portfolio_simulations import (
    CONFIG,
    _build_entry_edge_masks,
    _is_entry_bar,
    run_portfolio_simulation,
)

DATES = pd.to_datetime([
    "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05",
    "2024-01-08", "2024-01-09", "2024-01-10",
])


def _sig(values, index=DATES):
    return pd.Series(values, index=index, dtype=float)


# --------------------------------------------------------------------------
# Pure: _build_entry_edge_masks
# --------------------------------------------------------------------------
class TestBuildEntryEdgeMasks:
    def test_only_the_transition_bar_is_an_edge(self):
        m = _build_entry_edge_masks({"X": _sig([0, 1, 1, 1, -1, 0, 0])})
        assert list(m["X"][1]) == [False, True, False, False, False, False, False]

    def test_first_bar_of_the_series_counts_as_an_edge(self):
        # a transition from nothing is still a transition
        m = _build_entry_edge_masks({"X": _sig([1, 1, 1, -1, 0, 0, 0])})
        assert bool(m["X"][1].iloc[0]) is True
        assert not m["X"][1].iloc[1:].any()

    def test_re_entry_after_an_exit_is_a_new_edge(self):
        m = _build_entry_edge_masks({"X": _sig([1, 1, -1, 0, 1, 1, 0])})
        assert list(m["X"][1]) == [True, False, False, False, True, False, False]

    def test_a_series_with_no_entries_has_no_edges(self):
        m = _build_entry_edge_masks({"X": _sig([0, 0, -1, 0, 0, 0, 0])})
        assert not m["X"][1].any()
        assert not m["X"][-2].any()

    def test_long_and_short_masks_are_independent(self):
        m = _build_entry_edge_masks({"X": _sig([1, 1, -1, -2, -2, -1, 0])})
        assert list(m["X"][1]) == [True, False, False, False, False, False, False]
        assert list(m["X"][-2]) == [False, False, False, True, False, False, False]

    def test_every_symbol_gets_a_mask(self):
        m = _build_entry_edge_masks({"A": _sig([1] * 7), "B": _sig([0] * 7)})
        assert set(m) == {"A", "B"}
        assert set(m["A"]) == {1, -2}


# --------------------------------------------------------------------------
# Pure: _is_entry_bar
# --------------------------------------------------------------------------
class TestIsEntryBar:
    def setup_method(self):
        self.signals = {"X": _sig([0, 1, 1, 1, -1, 0, 0])}
        self.masks = _build_entry_edge_masks(self.signals)

    def test_level_mode_accepts_any_bar_holding_the_value(self):
        # edge_masks=None -> the original equality test
        assert _is_entry_bar(self.signals, None, "X", DATES[1], 1) is True
        assert _is_entry_bar(self.signals, None, "X", DATES[3], 1) is True

    def test_edge_mode_accepts_only_the_transition(self):
        assert _is_entry_bar(self.signals, self.masks, "X", DATES[1], 1) is True
        assert _is_entry_bar(self.signals, self.masks, "X", DATES[3], 1) is False

    def test_wrong_value_is_rejected_in_both_modes(self):
        for masks in (None, self.masks):
            assert _is_entry_bar(self.signals, masks, "X", DATES[0], 1) is False
            assert _is_entry_bar(self.signals, masks, "X", DATES[1], -2) is False

    @pytest.mark.parametrize("bad_date", [pd.NaT, pd.Timestamp("2020-06-01")])
    def test_missing_or_nat_date_is_rejected(self, bad_date):
        assert _is_entry_bar(self.signals, self.masks, "X", bad_date, 1) is False
        assert _is_entry_bar(self.signals, None, "X", bad_date, 1) is False

    def test_symbol_absent_from_signals_is_rejected(self):
        assert _is_entry_bar(self.signals, self.masks, "NOPE", DATES[1], 1) is False
        assert _is_entry_bar(self.signals, None, "NOPE", DATES[1], 1) is False

    def test_symbol_absent_from_the_MASKS_is_rejected_not_raised(self):
        """@zachisit on review: `signals` was guarded and `edge_masks` was not.

        In-tree both are built from the same dict so this cannot fire, but a
        subset of masks would have surfaced as a KeyError deep inside the date
        loop instead of as a skipped entry. Both guards now agree.
        """
        partial = _build_entry_edge_masks({"OTHER": _sig([1] * 7)})
        assert _is_entry_bar(self.signals, partial, "X", DATES[1], 1) is False


# --------------------------------------------------------------------------
# Engine wiring
# --------------------------------------------------------------------------
def _frame(px=100.0, n=7):
    return pd.DataFrame(
        {"Open": [px] * n, "High": [px * 1.01] * n, "Low": [px * 0.99] * n,
         "Close": [px] * n, "Volume": [50_000_000] * n,
         "ATR_14": [1.0] * n, "RSI_14": [50.0] * n, "SMA_200": [px] * n},
        index=DATES[:n],
    )


def _run(portfolio_data, signals, mode, allocation_pct=1.0):
    # Exhaust buying power in the starvation scenarios. At 0.99 the remaining
    # cash can fund a small second position; those scenarios only looked
    # starved while the affordability round-trip incorrectly rejected it.
    with patch.dict(CONFIG, {"entry_trigger": mode}):
        res = run_portfolio_simulation(
            portfolio_data, signals, 100_000.0, allocation_pct,
            None, None, None, {"type": "none"},
        )
    return pd.DataFrame(res["trade_log"])


# AAA holds all the cash for exactly one bar, then releases it. BBB's signal is a
# forward-filled state series whose only real breakout is the first bar.
_STARVED_DATA = {"AAA": _frame(), "BBB": _frame()}
_STARVED_SIGS = {
    "AAA": _sig([1, -1, 0, 0, 0, 0, 0]),
    "BBB": _sig([1, 1, 1, 1, 1, -1, 0]),
}


class TestDefaultIsEdge:
    """Flipped by #401. Both the shipped value and the engine's fallback for a
    config missing the key must be "edge". The fallback is pinned by behaviour
    (see ``TestEdgeModeDisablesStopReEntry``), not by grepping the source."""

    def test_shipped_config_is_edge(self):
        # Index, not .get(): a .get with an "edge" default would pass on a
        # config.py that dropped the key entirely.
        assert str(CONFIG["entry_trigger"]).lower() == "edge"


class TestLevelModeIsUnchanged:
    def test_uncontested_entry_is_identical_in_both_modes(self):
        """With cash free on the breakout bar the two modes must agree exactly.

        This is the no-regression invariant, and it is stated PER SYMBOL: for a
        symbol whose breakout bar had capital available, edge mode changes
        nothing. It does NOT generalise to the book -- see
        ``test_edge_mode_can_admit_a_breakout_level_mode_starved``, which is the
        other half of what this option does.
        """
        data = {"BBB": _frame()}
        sigs = {"BBB": _sig([1, 1, 1, 1, 1, -1, 0])}
        lvl, edg = _run(data, sigs, "level"), _run(data, sigs, "edge")
        assert len(lvl) == len(edg) == 1
        assert lvl.iloc[0]["EntryDate"] == edg.iloc[0]["EntryDate"]
        assert lvl.iloc[0]["ExitDate"] == edg.iloc[0]["ExitDate"]

    def test_level_mode_enters_a_hold_bar_when_capital_frees_up(self):
        """The defect, pinned. BBB's breakout was 01-02 (fill 01-03), but AAA
        held the cash. Level mode enters on 01-04 off a *hold* bar instead."""
        log = _run(_STARVED_DATA, _STARVED_SIGS, "level")
        assert sorted(log["Symbol"]) == ["AAA", "BBB"]
        bbb = log[log["Symbol"] == "BBB"].iloc[0]
        assert pd.Timestamp(bbb["EntryDate"]) == pd.Timestamp("2024-01-04")


class TestEdgeModePreventsLateEntry:
    def test_edge_mode_skips_rather_than_enters_late(self):
        log = _run(_STARVED_DATA, _STARVED_SIGS, "edge")
        assert sorted(log["Symbol"]) == ["AAA"]

    def test_the_two_modes_differ_only_on_the_starved_symbol(self):
        lvl = _run(_STARVED_DATA, _STARVED_SIGS, "level")
        edg = _run(_STARVED_DATA, _STARVED_SIGS, "edge")
        aaa_l = lvl[lvl["Symbol"] == "AAA"].iloc[0]
        aaa_e = edg[edg["Symbol"] == "AAA"].iloc[0]
        assert aaa_l["EntryDate"] == aaa_e["EntryDate"]
        assert aaa_l["ExitDate"] == aaa_e["ExitDate"]
        assert aaa_l["Profit"] == pytest.approx(aaa_e["Profit"])

    def test_signal_date_priority_queue_also_respects_edge_mode(self):
        """The priority sort key is a second wiring site; if it kept testing the
        level it would rank hold bars ahead of genuine breakouts."""
        with patch.dict(CONFIG, {"entry_priority": "signal_date"}):
            lvl = _run(_STARVED_DATA, _STARVED_SIGS, "level")
            edg = _run(_STARVED_DATA, _STARVED_SIGS, "edge")
        assert sorted(lvl["Symbol"]) == ["AAA", "BBB"]
        assert sorted(edg["Symbol"]) == ["AAA"]


class TestEdgeModeReallocatesCapitalRatherThanOnlySkippingEntries:
    """Freeing capital is not a side effect -- it is the same resource the
    starvation defect is about. Skipping a hold-bar entry hands its allocation
    to whatever else is competing on that bar, so edge mode changes the SIZE of
    a surviving trade, not only the membership of the book.

    Measured over 80 randomised contested books (5 symbols x 120 bars): 20 of
    the 80 produced at least one symbol with MORE trades under edge than under
    level -- 25 of 400 (book, symbol) cells -- while book totals fell 1564 ->
    1434. So the net effect subtracts, but it is a re-plan, not a filter.
    """

    # AAA holds all the cash for one bar. BBB's only real breakout is bar 0;
    # everything after is a forward-filled hold. CCC's breakout is genuine and
    # lands on the bar the cash frees up -- so the two compete, and under level
    # mode BBB's HOLD bar wins the tie-break and takes the allocation.
    DATA = {"AAA": _frame(), "BBB": _frame(), "CCC": _frame()}
    SIGS = {
        "AAA": _sig([1, -1, 0, 0, 0, 0, 0]),
        "BBB": _sig([1, 1, 1, 1, 1, -1, 0]),
        "CCC": _sig([0, 1, 1, -1, 0, 0, 0]),
    }

    def _ccc_shares(self, mode):
        log = _run(self.DATA, self.SIGS, mode)
        row = log[log["Symbol"] == "CCC"]
        if row.empty:
            return 0.0
        assert len(row) == 1, "CCC should trade at most once in %s mode" % mode
        return float(row.iloc[0]["Shares"])

    def test_level_mode_lets_a_hold_bar_take_a_breakouts_allocation(self):
        """BBB's hold bar consumes the released cash before CCC's breakout.

        Any rounding residual is too small to fund the minimum share count.
        """
        log = _run(self.DATA, self.SIGS, "level")
        assert sorted(log["Symbol"]) == ["AAA", "BBB"]
        assert self._ccc_shares("level") == 0.0

    def test_edge_mode_gives_that_allocation_back_to_the_breakout(self):
        """A fresh breakout gets the position when the hold bar is refused."""
        log = _run(self.DATA, self.SIGS, "edge")
        assert sorted(log["Symbol"]) == ["AAA", "CCC"]
        assert self._ccc_shares("edge") > 900.0

    def test_the_reallocation_restores_a_full_position(self):
        assert self._ccc_shares("edge") - self._ccc_shares("level") > 900.0


def _frame_px(closes):
    n = len(closes)
    idx = pd.bdate_range("2024-01-02", periods=n)
    return pd.DataFrame(
        {"Open": closes, "High": [c * 1.005 for c in closes],
         "Low": [c * 0.995 for c in closes], "Close": closes,
         "Volume": [50_000_000] * n, "ATR_14": [1.0] * n,
         "RSI_14": [50.0] * n, "SMA_200": closes},
        index=idx,
    ), idx


class TestEdgeModeDisablesStopReEntry:
    """The second consequence of edge mode, and the larger one on a stopped
    strategy: a stop-out under a still-held state signal never re-enters.

    Level mode re-enters on the very next bar because the forward-filled series
    still reads 1. Edge mode cannot -- the transition already happened. A live
    scanner triggering on `last == 1 and prev != 1` behaves the same way, so
    this is edge mode being faithful rather than lossy, but it is an
    independent semantic change and belongs under test rather than only in a
    config comment.
    """

    CLOSES = [100.0, 100.0, 90.0, 100.0, 100.0, 100.0, 100.0, 100.0]
    STOP = {"type": "percentage", "value": 0.05}

    def _run_stop(self, mode):
        frame, idx = _frame_px(self.CLOSES)
        sigs = {"X": pd.Series([1.0] * (len(self.CLOSES) - 1) + [-1.0],
                               index=idx, dtype=float)}
        with patch.dict(CONFIG, {"entry_trigger": mode}):
            if mode == "__missing__":
                del CONFIG["entry_trigger"]
            res = run_portfolio_simulation(
                {"X": frame}, sigs, 100_000.0, 0.95,
                None, None, None, self.STOP,
            )
        return pd.DataFrame(res["trade_log"])

    def test_level_mode_stops_out_and_gets_straight_back_in(self):
        log = self._run_stop("level")
        assert len(log) == 2
        assert "Stop Loss" in str(log.iloc[0]["ExitReason"])

    def test_edge_mode_stops_out_and_stays_out(self):
        log = self._run_stop("edge")
        assert len(log) == 1
        assert "Stop Loss" in str(log.iloc[0]["ExitReason"])

    @pytest.mark.parametrize("value", ["edges", "Edge ", "pulse", None, " LEVEL "])
    def test_only_an_explicit_level_runs_level(self, value):
        """The engine used to build edge masks only for an exact "edge", so
        every unrecognised value -- a typo, None -- ran LEVEL while the
        validator said it fell back to edge (adversarial QA on #405). Now
        only "level" (case/whitespace-insensitive) selects level."""
        log = self._run_stop(value)
        expected = 2 if str(value).strip().lower() == "level" else 1
        assert len(log) == expected, (value, len(log))

    def test_a_config_missing_the_key_behaves_as_edge(self):
        """The engine fallback (#401). A config written before the key existed
        must get the shipped default, not the semantics it was flipped away
        from -- this fails if the fallback reverts to "level"."""
        log = self._run_stop("__missing__")
        assert len(log) == 1
        assert "Stop Loss" in str(log.iloc[0]["ExitReason"])


class TestHoldStateShort:
    """-2 is the short-ENTRY value; on a bar already short it means "hold".
    The engine covered on ANY negative signal, -2 included, so a hold-state
    short covered every bar: level churned a round trip per bar, and the edge
    default refused the re-entry, leaving the book flat after one bar --
    signal [-2]*8 + [-1, 0] gave 8 trades under level, 1 one-bar trade under
    edge (adversarial QA on #405)."""

    @pytest.mark.parametrize("mode", ["level", "edge"])
    def test_held_short_is_one_trade_held_to_the_cover(self, mode):
        frame, idx = _frame_px([100.0] * 10)
        sig = pd.Series([-2.0] * 8 + [-1.0, 0.0], index=idx)
        with patch.dict(CONFIG, {"entry_trigger": mode, "execution_time": "close"}):
            res = run_portfolio_simulation(
                {"X": frame}, {"X": sig}, 100_000.0, 0.5,
                None, None, None, {"type": "none"})
        log = pd.DataFrame(res["trade_log"])
        assert len(log) == 1, log[["EntryDate", "ExitDate"]]
        assert log.iloc[0]["ExitReason"] == "Short Cover"
        assert pd.Timestamp(log.iloc[0]["ExitDate"]) == idx[8]


    def test_a_second_minus_2_pulse_does_not_reshort(self):
        """[0,-2,0,0,-2,0,0,-1] used to cover and re-open on the second -2,
        resetting the entry price and stop (2 trades). -2 never covers, so it
        is one short held to the -1, in both modes."""
        frame, idx = _frame_px([100.0] * 8)
        sig = pd.Series([0, -2, 0, 0, -2, 0, 0, -1], index=idx, dtype=float)
        for mode in ("level", "edge"):
            with patch.dict(CONFIG, {"entry_trigger": mode, "execution_time": "close"}):
                res = run_portfolio_simulation(
                    {"X": frame}, {"X": sig}, 100_000.0, 0.5,
                    None, None, None, {"type": "none"})
            log = pd.DataFrame(res["trade_log"])
            assert len(log) == 1, (mode, len(log))

    def test_short_to_long_needs_a_cover_bar(self):
        """Documented asymmetry, pinned: -2 exits a long (it is <= -1), but 1
        does not cover a short (#313's long-over-short guard), so a direct
        -2 -> 1 holds the short. A flip is -1 then 1."""
        frame, idx = _frame_px([100.0] * 10)
        sig = pd.Series([0, -2, -2, -2, 1, 1, 1, 1, 1, 0], index=idx, dtype=float)
        with patch.dict(CONFIG, {"entry_trigger": "edge", "execution_time": "close"}):
            res = run_portfolio_simulation(
                {"X": frame}, {"X": sig}, 100_000.0, 0.5,
                None, None, None, {"type": "none"})
        log = pd.DataFrame(res["trade_log"])
        assert len(log) == 1 and str(log.iloc[0]["Trade"]).startswith("Short")


class TestFreshSignalOnTheStopBar:
    """Pinned as-is, NOT endorsed. #401's review measured that a fresh 1
    emitted ON the stop bar ({1: 1, 5: 1}) enters that bar in both modes --
    bar 4 reads 0, so bar 5 is a genuine transition. Under execution_time
    "close" that is executable; under "open" it books an entry at the open of
    a bar whose stop fired intrabar, which is the narrow follow-up #401 split
    out. This pins the current behaviour so that follow-up visibly flips it."""

    CLOSES = [100.0, 101.0, 102.0, 101.0, 100.0, 94.0, 95.0, 96.0, 97.0, 98.0]

    @pytest.mark.parametrize("mode", ["level", "edge"])
    def test_fresh_entry_on_the_stop_bar_enters(self, mode):
        frame, idx = _frame_px(self.CLOSES)
        sig = pd.Series(0.0, index=idx)
        sig.iloc[1] = 1
        sig.iloc[5] = 1
        with patch.dict(CONFIG, {"entry_trigger": mode, "execution_time": "close"}):
            res = run_portfolio_simulation(
                {"X": frame}, {"X": sig}, 100_000.0, 0.5,
                None, None, None, {"type": "percentage", "value": 0.05})
        log = pd.DataFrame(res["trade_log"])
        assert len(log) == 2, log[["EntryDate", "ExitDate", "ExitReason"]]
        assert "Stop Loss" in str(log.iloc[0]["ExitReason"])
        assert log.iloc[1]["EntryDate"] == log.iloc[0]["ExitDate"]


class TestShortSide:
    """A forward-filled SHORT state series no longer churns in either mode.

    ``-2`` used to satisfy both the entry test (``== -2``) and the cover test
    (``< 0``), so under level each hold bar covered and re-opened the short.
    The cover test now excludes -2 (#405 QA, see TestHoldStateShort), so the
    churn is gone at its source and both modes hold one short to the -1.
    """

    DATA = {"SSS": _frame()}
    SIGS = {"SSS": _sig([-2, -2, -2, -2, -1, 0, 0])}

    def test_level_mode_no_longer_churns(self):
        """FLIPPED: this pinned 4 round trips (the churn) before the cover test
        stopped treating -2 as a cover."""
        log = _run(self.DATA, self.SIGS, "level", allocation_pct=0.5)
        assert len(log) == 1
        assert str(log.iloc[0]["Trade"]).startswith("Short")

    def test_edge_mode_opens_the_short_once(self):
        log = _run(self.DATA, self.SIGS, "edge", allocation_pct=0.5)
        assert len(log) == 1
        assert pd.Timestamp(log.iloc[0]["EntryDate"]) == pd.Timestamp("2024-01-03")

    def test_a_clean_short_signal_is_unaffected_by_the_mode(self):
        """One -2 followed by flat bars: nothing to churn, modes must agree."""
        data, sigs = {"SSS": _frame()}, {"SSS": _sig([-2, 0, 0, -1, 0, 0, 0])}
        lvl = _run(data, sigs, "level", allocation_pct=0.5)
        edg = _run(data, sigs, "edge", allocation_pct=0.5)
        assert len(lvl) == len(edg) == 1
        assert lvl.iloc[0]["EntryDate"] == edg.iloc[0]["EntryDate"]
        assert lvl.iloc[0]["ExitDate"] == edg.iloc[0]["ExitDate"]


# --------------------------------------------------------------------------
# Config validation
# --------------------------------------------------------------------------
class TestConfigValidation:
    def test_known_values_produce_no_entry_trigger_warning(self):
        for value in ("level", "edge", "EDGE", " edge "):
            warns = validate_config({"entry_trigger": value})
            assert not [w for w in warns if "entry_trigger" in w]

    def test_a_typo_is_caught_at_startup(self):
        """Someone who meant "level" and typed "levle" gets edge; they must be
        told, and told the truth about which mode they got."""
        warns = validate_config({"entry_trigger": "edges"})
        msgs = [w for w in warns if "entry_trigger" in w]
        assert msgs and "fall back to 'edge'" in msgs[0], msgs

    def test_an_explicit_none_is_unset_not_a_typo(self):
        """``None`` means "unset" for every key the validator knows, and the
        engine now runs it as the shipped default "edge" (it used to run LEVEL
        -- adversarial QA on #405), so it needs no warning. The engine half is
        pinned by test_only_an_explicit_level_runs_level[None]."""
        assert not [w for w in validate_config({"entry_trigger": None})
                    if "entry_trigger" in w]

    def test_absent_key_is_not_a_warning(self):
        assert not [w for w in validate_config({}) if "entry_trigger" in w]
