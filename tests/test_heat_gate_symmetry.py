# tests/test_heat_gate_symmetry.py
"""Portfolio-heat gate must see the whole book, from every entry path.

QA findings F1/F2 on PR #324.

#312 gave equity shorts a `risk` key so they contribute to the heat pot. But
only the SHORT entry gate was updated to read it: the long entry still passed
`positions` alone, and the futures short branch had no gate and registered no
risk at all. Net effect on a mixed book:

    2.0% of risk against a 1.5% cap
      -> entering SHORT: rejected
      -> entering LONG:  admitted

i.e. the cap was breachable through the long side, and admit/reject depended on
entry ORDER and DIRECTION. That is the inconsistency #312's own QA note set out
to remove ("gate against BOTH open longs and open shorts") - it landed in one
branch and not the others.

These tests pin the invariant directly rather than through a full simulation:
the gate is a pure function, and the defect was always in WHICH BOOK gets passed
to it, not in its arithmetic.
"""

import ast
import os
import re

import pytest

from helpers.position_sizing import check_portfolio_heat

SIM = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "helpers", "portfolio_simulations.py")


class TestGateArithmeticIsDirectionBlind:
    """The invariant, stated as a property: admitting a new position must depend
    on the risk already on the book, never on how that risk was acquired."""

    EQ = 100_000.0
    CAP = 0.015          # 1.5%
    NEW = 1_000.0        # 1% of equity

    def test_one_percent_of_open_risk_blocks_a_one_percent_entry(self):
        book = {"AAA": {"risk": 1_000.0}}
        assert check_portfolio_heat(book, self.NEW, self.EQ, self.CAP) is False

    def test_same_risk_admits_when_it_fits(self):
        book = {"AAA": {"risk": 400.0}}
        assert check_portfolio_heat(book, self.NEW, self.EQ, self.CAP) is True

    @pytest.mark.parametrize("book", [
        {"AAA": {"risk": 1_000.0}},                     # one long
        {"SSS": {"risk": 1_000.0}},                     # one short
        {"AAA": {"risk": 500.0}, "SSS": {"risk": 500.0}},   # one of each
    ])
    def test_identical_total_risk_gives_an_identical_verdict(self, book):
        """1% of open risk is 1% of open risk. Long, short, or split - the gate
        must not care. This is what makes passing the MERGED book correct and
        passing either half wrong."""
        assert check_portfolio_heat(book, self.NEW, self.EQ, self.CAP) is False

    def test_passing_only_half_the_book_is_what_broke_it(self):
        """Demonstrates the defect shape: with risk held on the short side,
        gating against `positions` alone (an empty dict) admits an entry that
        the merged book rejects."""
        longs, shorts = {}, {"SSS": {"risk": 1_000.0}}
        merged_verdict = check_portfolio_heat({**longs, **shorts}, self.NEW,
                                              self.EQ, self.CAP)
        longs_only_verdict = check_portfolio_heat(longs, self.NEW,
                                                 self.EQ, self.CAP)
        assert merged_verdict is False
        assert longs_only_verdict is True
        assert merged_verdict != longs_only_verdict


class TestEveryEntryPathGatesAgainstTheMergedBook:
    """Source-level pins. The gate is called from three entry paths; all three
    must pass the merged book. Asserted against the source because the defect
    was an argument at a call site, and a behavioural test would need a full
    mixed-book simulation per path to reach the same conclusion.
    """

    @staticmethod
    def _heat_calls():
        src = open(SIM, encoding="utf-8").read()
        tree = ast.parse(src)
        calls = []
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "check_portfolio_heat"):
                calls.append(node)
        return src, calls

    def test_there_are_three_gated_entry_paths(self):
        """Long, equity short, futures short. If this count changes, a new entry
        path was added and needs the same treatment."""
        _, calls = self._heat_calls()
        assert len(calls) == 3, f"expected 3 heat gates, found {len(calls)}"

    def test_every_call_passes_the_merged_book(self):
        """No call may pass `positions` or `short_positions` alone."""
        src, calls = self._heat_calls()
        for call in calls:
            first = call.args[0]
            rendered = ast.get_source_segment(src, first)
            assert isinstance(first, ast.Dict), (
                f"heat gate at line {call.lineno} passes {rendered!r}, not a "
                f"merged dict - it can only see half the book"
            )
            keys = [k for k in first.keys if k is None]   # ** unpacking
            assert len(keys) == 2, (
                f"heat gate at line {call.lineno} unpacks {len(keys)} dict(s), "
                f"expected both positions and short_positions: {rendered!r}"
            )
            assert "positions" in rendered and "short_positions" in rendered, (
                f"heat gate at line {call.lineno} does not merge both books: "
                f"{rendered!r}"
            )

    def test_futures_short_registers_its_risk(self):
        """A gate that reads `risk` is useless if an entry path never writes it:
        the position would be admitted, then contribute 0 to every later gate.
        The futures short branch previously had neither."""
        src = open(SIM, encoding="utf-8").read()
        assert "'risk': _fs_new_risk" in src, (
            "futures short entry does not register a 'risk' key - it will "
            "contribute 0 to the heat pot for every subsequent entry"
        )

    def test_equity_short_still_registers_its_risk(self):
        src = open(SIM, encoding="utf-8").read()
        assert "'risk': _s_new_risk" in src


class TestWeekdayOvernightDocstringMatchesBehaviour:
    """QA finding F3. The docstring claimed the strategy stays flat across
    'weekends AND exchange holidays (Good Friday, Thanksgiving, ...)'. Its own
    test asserts a midweek holiday is HELD - a lone Thursday closure leaves a
    2-day Wed->Fri gap, and the rule is `> 2`. Good Friday only works because it
    abuts a weekend."""

    def test_docstring_no_longer_claims_thanksgiving_is_avoided(self):
        from helpers.indicators import weekday_overnight_logic
        doc = weekday_overnight_logic.__doc__
        assert doc is not None
        # The corrected docstring must state the threshold and the consequence.
        assert "> 2" in doc or "2 calendar days" in doc
        assert "HELD" in doc, (
            "docstring must say a lone midweek holiday is held, since that is "
            "what the > 2 threshold does and what the tests assert"
        )

    def test_docstring_does_not_promise_blanket_holiday_flatness(self):
        from helpers.indicators import weekday_overnight_logic
        doc = weekday_overnight_logic.__doc__
        # The old wording paired "flat across" with a holiday list including
        # Thanksgiving. Guard against that exact overclaim returning.
        flat_holiday_claim = re.search(
            r"flat across\s+weekends AND exchange holidays", doc)
        assert flat_holiday_claim is None, (
            "docstring again claims blanket holiday flatness, which the > 2 "
            "day gap threshold does not deliver for midweek closures"
        )


class TestPositionsAndShortsStayDisjoint:
    """@shardul0701's finding on #344: F1's fix is only safe because of #313.

    `check_portfolio_heat` sums over `.values()` of a SINGLE dict, so
    `{**positions, **short_positions}` merges **by symbol** — a symbol present in
    both contributes once, and the short leg REPLACES the long leg rather than
    adding to it:

        long AAPL risk 3%  +  short AAPL risk 4%
        sum over the merged dict                  = 4%   <- long leg dropped
        true combined exposure                    = 7%

    So on a tree where a symbol can be long and short at once, the merged-book
    gate stops over-counting and starts UNDER-counting — it fails OPEN, which is
    strictly worse than the bug it fixes, and silently.

    It is safe here because #313's guard (`if symbol in positions or symbol in
    short_positions: continue`) keeps the two dicts disjoint. That invariant is
    load-bearing for the heat gate and was previously undocumented and
    unasserted, so relaxing the guard later — to allow a deliberately hedged
    book, say — would silently re-open this with no failing test.
    """

    def test_merged_dict_drops_a_leg_when_a_symbol_is_in_both(self):
        """The hazard itself, stated so the dependency is visible in code."""
        longs = {"AAPL": {"risk": 3000.0}}
        shorts = {"AAPL": {"risk": 4000.0}}
        merged = {**longs, **shorts}
        assert list(merged.keys()) == ["AAPL"]
        assert merged["AAPL"]["risk"] == 4000.0          # long leg gone
        assert sum(p["risk"] for p in merged.values()) == 4000.0
        assert 3000.0 + 4000.0 == 7000.0                  # true exposure

    def test_that_hazard_would_make_the_gate_fail_open(self):
        """Under-counting admits an entry the true exposure would reject —
        worse than the over-count F1 fixed."""
        merged = {**{"AAPL": {"risk": 3000.0}}, **{"AAPL": {"risk": 4000.0}}}
        true_book = {"L": {"risk": 3000.0}, "S": {"risk": 4000.0}}
        assert check_portfolio_heat(merged, 1000.0, 100_000.0, 0.05) is True
        assert check_portfolio_heat(true_book, 1000.0, 100_000.0, 0.05) is False

    def test_long_entry_is_guarded_against_symbols_held_short(self):
        """#313's guard is what keeps the dicts disjoint. If this assertion
        fails, the F1 heat fix above becomes unsafe — they are coupled."""
        src = open(SIM, encoding="utf-8").read()
        assert "if symbol in positions or symbol in short_positions" in src, (
            "the long-entry guard (#313) is gone — with it, a symbol can be "
            "long and short at once and the merged-book heat gate silently "
            "under-counts. Do not relax this without reworking the gate to sum "
            "the two books separately."
        )

    def test_short_entry_is_guarded_too(self):
        src = open(SIM, encoding="utf-8").read()
        assert re.search(r"symbol in positions or symbol in short_positions", src)


class TestAtrAnchorsToTheSignalBarInBothExecutionModes:
    """@shardul0701's remaining finding on #324: the #310 defect class survived
    in three branches the epic did not touch.

    `entry_exec_date = date` unconditionally, while `signal_date` is the bar
    before the fill under `execution_time="open"` and the fill bar itself under
    `"close"`. Three sites hard-coded `prev_trading_dates[entry_exec_date]`,
    which is the signal bar ONLY under "open" — under "close" it reads one bar
    too early. Measured: a 10x difference in stop distance (97.00 vs 70.00) on
    identical inputs, from the execution mode alone.

    Not look-ahead — the data is strictly in the past — but the wrong bar, and
    unlike #310 it moves P&L: the level sets the exit price and `InitialRisk`,
    hence every R-multiple, expectancy and SQN downstream, and two of the three
    sites set the SHARE COUNT.

    Already documented in CLAUDE.md:243-245 as a known divergence; it just never
    became a ticket. And no test in the suite set `execution_time="close"` with
    an ATR stop, so nothing locked in the wrong behaviour.
    """

    @pytest.mark.parametrize("site", [
        "day_before_entry = signal_date",     # atr stop level
    ])
    def test_atr_stop_level_anchors_to_signal_date(self, site):
        src = open(SIM, encoding="utf-8").read()
        assert site in src

    def test_both_risk_sizing_branches_anchor_to_signal_date(self):
        """trailing_atr and atr sizing — these set the share count."""
        src = open(SIM, encoding="utf-8").read()
        assert src.count("_dbe_sz = signal_date") == 2, (
            "expected both the trailing_atr and atr sizing branches to anchor "
            "to signal_date"
        )

    def test_no_atr_branch_still_hardcodes_prev_of_the_fill_bar(self):
        """The regression guard. `prev_trading_dates[...].get(entry_exec_date)`
        is correct ONLY under execution_time='open'; any ATR/sizing branch using
        it is wrong in close mode."""
        src = open(SIM, encoding="utf-8").read()
        tree = ast.parse(src)
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            seg = ast.get_source_segment(src, node) or ""
            if "prev_trading_dates" in seg and "entry_exec_date" in seg:
                offenders.append((node.lineno, seg.strip()[:70]))
        # The stop-loss *trailing* update and the MTM paths legitimately use the
        # fill bar; only the three ATR anchor/sizing sites were wrong, and those
        # now use signal_date. Assert none of the remaining ones read ATR_14.
        for lineno, seg in offenders:
            following = src.splitlines()[lineno:lineno + 6]
            assert not any("ATR_14" in l for l in following), (
                f"line {lineno} anchors an ATR read to prev(fill bar): {seg!r} — "
                f"wrong under execution_time='close'"
            )
