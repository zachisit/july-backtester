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
