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
from datetime import date

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

    # DELETED: test_both_risk_sizing_branches_anchor_to_signal_date.
    #
    # It asserted `src.count("_dbe_sz = signal_date") == 2` — a source-text
    # count on a PRIVATE LOCAL VARIABLE NAME. It broke the moment the epic
    # spelled the same fix inline without the temporary, and it would break
    # again on any rename, while saying nothing about behaviour either way.
    # The widened grid in tests/test_atr_logic.py now covers both sites
    # behaviourally — reverting either anchor fails it — so this pinned a
    # spelling and nothing else. @shardul0701 called it; he is right.

    def test_no_atr_branch_still_hardcodes_prev_of_the_fill_bar(self):
        """The regression guard, generalised.

        The first version keyed on `prev_trading_dates` AND `entry_exec_date`.
        That name exists only on the LONG entry path -- the short block calls
        the fill bar `date` -- so the guard was structurally blind to half the
        file it guards, and reported a clean sweep while two short-side ATR
        anchors were still wrong. Caught by @shardul0701 on #344, not by this.

        Now it flags any assignment that indexes `prev_trading_dates` with
        ANYTHING other than an execution-aware variable, whenever an ATR read
        follows. The execution-aware names are `signal_date` (long) and
        `sig_date` (short); both carry the `execution_time` ternary.
        """
        src = open(SIM, encoding="utf-8").read()
        tree = ast.parse(src)
        EXEC_AWARE = ("signal_date", "sig_date")
        offenders = []
        for node in ast.walk(tree):
            # `ast.Assign` ONLY made this guard structurally blind a SECOND
            # time. The epic spelled the same anchors inline —
            # `df.loc[signal_date].get('ATR_14')` inside an `if`, no assignment
            # node — and the guard reported a clean sweep across all three.
            #
            # It has now been blind twice: first to the short entry path
            # (keyed on `entry_exec_date`, a name that path never uses), then
            # to inline anchors (keyed on a node type the code stopped using).
            # Both times it said everything was fine. The lesson is that a
            # guard keyed on how code is *spelled* fails silently whenever the
            # spelling moves, so key it as broadly as the thing it protects:
            # any node that mentions prev_trading_dates at all.
            if not isinstance(node, (ast.Assign, ast.If, ast.Expr,
                                     ast.Call, ast.Subscript, ast.Compare)):
                continue
            seg = ast.get_source_segment(src, node) or ""
            if "prev_trading_dates" not in seg:
                continue
            # An execution-aware lookup is fine -- that is how signal_date and
            # sig_date are themselves defined.
            if any(name in seg for name in EXEC_AWARE):
                continue
            offenders.append((node.lineno, seg.strip()[:70]))
        # The stop-loss *trailing* update and the MTM paths legitimately use the
        # fill bar; only the three ATR anchor/sizing sites were wrong, and those
        # now use signal_date. Assert none of the remaining ones read ATR_14.
        for lineno, seg in offenders:
            # lineno - 1, not lineno: ast lineno is 1-based and splitlines() is
            # 0-based, so [lineno] starts at the line AFTER the offending node
            # and the window never reads the offender's own line. A single-line
            # inline anchor carries both `prev_trading_dates` and `ATR_14` on
            # that one skipped line, so the guard reported a clean sweep against
            # a live defect. Verified on merged main: injecting
            # `_atr_tp = df.loc[prev_trading_dates[entry_exec_date], 'ATR_14']`
            # left this file at 35 passed while test_atr_logic.py failed.
            #
            # THIRD time this guard has been blind while reporting clean --
            # first keyed on `entry_exec_date` (a name the short path never
            # uses), then on `ast.Assign` (a node type the code stopped using),
            # now on a window that excludes the line it is judging. The rule
            # generalises: a guard keyed on how code is SPELLED fails silently
            # the moment the spelling moves -- including onto one line.
            following = src.splitlines()[lineno - 1:lineno + 6]
            assert not any("ATR_14" in l for l in following), (
                f"line {lineno} anchors an ATR read to prev(fill bar): {seg!r} — "
                f"wrong under execution_time='close'"
            )


class TestWeekdayOvernightGapArithmeticIsPinned:
    """@shardul0701's finding 2 on #344: my correction to the F3 docstring
    introduced a NEW false claim, in the PR whose purpose was fixing false
    claims.

    I wrote that changing `> 2` to `>= 2` "would also flatten across every
    normal weeknight". A weeknight gap is **1** calendar day and `1 >= 2` is
    False, so it changes nothing about weeknights — it flips exactly the 2-day
    midweek-holiday rows, which is precisely what the preceding sentence said
    the change would be *for*. The stated consequence was the only argument
    given against making it, and it was wrong.

    I also wrote "Memorial / Labor Day  3 days". Both are MONDAY closures, so
    the gap is Fri -> Tue = **4** days. 3 is the plain-weekend value.

    Prose about arithmetic keeps being wrong here, so the arithmetic is now
    asserted rather than described.
    """

    # (label, calendar-day gap between consecutive SESSIONS)
    # DATES are the input; the gap is DERIVED. Previously this table hard-coded
    # both the gap AND the expected flag, and the assertion compared them to
    # each other -- so it could not tell 4 from 3. @shardul0701 proved it by
    # putting my original error back (Memorial row 4 -> 3): all three
    # CASES-dependent tests still passed, because `3 > 2` is True and `flat` was
    # True. The fact that was actually wrong -- how many calendar days that gap
    # spans -- was the hard-coded input, so a wrong belief was encoded and
    # confirmed by the same number.
    #
    # All dates are real 2026 sessions around the named closure.
    CASES = [
        ("normal weeknight  Tue->Wed", "2026-05-19", "2026-05-20", False),
        ("normal weekend    Fri->Mon", "2026-05-15", "2026-05-18", True),
        ("Good Friday       Thu->Mon", "2026-04-02", "2026-04-06", True),
        ("Memorial/Labor    Fri->Tue", "2026-05-22", "2026-05-26", True),
        ("Thanksgiving      Wed->Fri", "2026-11-25", "2026-11-27", False),
        # 2019, not 2020. July 4 2020 fell on a SATURDAY, so the market closed
        # Friday 2020-07-03 -- meaning the old row's second date was not a
        # session at all, and 2020-07-02 -> 2020-07-06 (gap 4, flat=True) is
        # the real consecutive pair across that holiday. The row asserted the
        # opposite and passed BOTH new guards: the derived gap agreed (2 days,
        # flat=False) and the weekday label agreed (07-01 is a Wed, 07-03 is a
        # Fri). "Are these consecutive SESSIONS" is not derivable from a plain
        # calendar -- weekdays come from a calendar, sessions come from an
        # EXCHANGE calendar, and this module has none. Caught by @shardul0701.
        # 2019 is correct on all three axes: real consecutive sessions, the
        # weekdays match the label, and July 4 genuinely falls on a Thursday.
        ("July 4th on Thu   Wed->Fri", "2019-07-03", "2019-07-05", False),
    ]

    @staticmethod
    def _gap(prev_session, next_session):
        """Calendar days between two sessions — computed, never asserted."""
        return (date.fromisoformat(next_session)
                - date.fromisoformat(prev_session)).days

    @pytest.mark.parametrize("label,prev_session,next_session,flat", CASES)
    def test_the_documented_table_matches_the_threshold(
            self, label, prev_session, next_session, flat):
        """Every row of the docstring table, checked against `> 2` — with the
        gap derived from the dates rather than supplied alongside the answer."""
        gap = self._gap(prev_session, next_session)
        assert (gap > 2) is flat, f"{label}: gap={gap}"

    @pytest.mark.parametrize("label,prev_session,next_session,flat", CASES)
    def test_each_rows_dates_are_the_weekdays_its_label_names(
            self, label, prev_session, next_session, flat):
        """The row's LABEL is the independent fact; the dates must match it.

        Deriving the gap from dates was not enough on its own — moving a date
        moves the gap, and if the hard-coded `flat` still agrees the row passes
        anyway. I checked: re-pointing the Memorial row at Fri->Mon (3 days)
        left all the gap tests green, which is the same defect one level down.

        `Fri->Tue` is a claim about weekdays, and weekday names come from the
        calendar rather than from this table, so a typo'd date fails here even
        when its gap happens to keep the threshold verdict intact.
        """
        names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        arrow = label.split()[-1]
        want_prev, want_next = arrow.split("->")
        got_prev = names[date.fromisoformat(prev_session).weekday()]
        got_next = names[date.fromisoformat(next_session).weekday()]
        assert (got_prev, got_next) == (want_prev, want_next), (
            f"{label}: dates are {got_prev}->{got_next} "
            f"({prev_session} -> {next_session})")

    def test_the_monday_closures_really_are_four_days(self):
        """The specific number I got wrong, now computed from a calendar.

        Memorial and Labor Day close a MONDAY, so Fri -> Tue spans 4 calendar
        days; 3 is the plain-weekend value. This is the assertion the old table
        could not make, because it was handed 4 and asked whether 4 > 2.
        """
        assert self._gap("2026-05-22", "2026-05-26") == 4
        assert self._gap("2026-05-15", "2026-05-18") == 3

    def test_ge_two_changes_only_the_midweek_holiday_rows(self):
        """The claim I got wrong, now pinned in both directions."""
        flipped = [l for l, p, n, _ in self.CASES
                   if (self._gap(p, n) >= 2) != (self._gap(p, n) > 2)]
        assert flipped == ["Thanksgiving      Wed->Fri", "July 4th on Thu   Wed->Fri"]

    def test_ge_two_does_not_touch_normal_weeknights(self):
        """The specific false claim — with the weeknight gap COMPUTED.

        This previously read `weeknight_gap = 1; assert (1 >= 2) is False`,
        which asserts arithmetic. The fact under test is that a weeknight
        session gap IS 1 calendar day, and that was the hard-coded input.
        """
        weeknight_gap = self._gap("2026-05-19", "2026-05-20")
        assert weeknight_gap == 1
        assert (weeknight_gap >= 2) is False
        assert (weeknight_gap > 2) is False

    def test_monday_closures_are_a_four_day_gap_not_three(self):
        """Memorial and Labor Day close a MONDAY, so Fri -> Tue is 4 days.
        3 is the plain-weekend value, and writing it was the same
        assert-by-prose defect F3 exists to fix."""
        from helpers.indicators import weekday_overnight_logic
        doc = weekday_overnight_logic.__doc__
        assert "Memorial/Labor   Fri->Tue      4" in doc or \
               re.search(r"Memorial/Labor\s+Fri->Tue\s+4", doc), (
            "docstring still records a Monday closure as a 3-day gap"
        )

    def test_docstring_no_longer_claims_ge2_affects_weeknights(self):
        from helpers.indicators import weekday_overnight_logic
        doc = weekday_overnight_logic.__doc__
        assert "flatten across every normal weeknight" not in doc, (
            "the >= 2 consequence is stated wrongly again: weeknights are a "
            "1-day gap and are unaffected"
        )
