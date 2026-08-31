"""The two long-entry stop-distance ladders must read the same stop_config keys.

`portfolio_simulations.py` resolves one physical quantity — the initial stop
distance — twice in the long entry block, ~90 lines apart: a FRACTION ladder for
`risk_parity` and a POINTS ladder for `risk_pct_capped`. Three separate
parameters have now drifted between them, each found by a different person on a
different ticket, each after the previous was called closed:

    stop type   #385 / #387   the points ladder had no `points` or `signal_bar`
                              branch at all — zero trades, silently
    bars_back   #390          the added `signal_bar` branch anchored to the
                              trigger bar; share count pinned regardless of the
                              parameter, UNBOUNDED over-risk
    buffer      #390          carried, but only by luck — hardcoding it to 0.0
                              passed 283 tests

Every one of those is a `stop_config` key present in one ladder and absent from
the other, so a set difference names it without knowing what it means. This test
needs no fixture, no price series and no execution mode.

It answers "is either ladder blind to a parameter the other honours", NOT "is a
shared key used correctly" — a branch that reads `buffer` and then adds it
instead of subtracting passes here. So it does not retire the value tests; it
makes REMOVAL loud, which is the form all three drifts actually took.
`TestBufferIsHonouredByBothLadders` below covers the value half for the one
parameter that is currently held only by luck.

Skips rather than fails if it cannot find both `if sizing_method == ...` blocks,
so it does not parse a pre-#384 tree and guess. That is also its exit condition:
**#391 deletes this file.** Hoisting the stop resolution above the sizing call
leaves one ladder, and a symmetry test over a single thing is vacuous. Until
then it is what stands between the fourth parameter and the fourth ticket.

Design, implementation and the commit-by-commit drift table are @shardul0701's
on #390.
"""

import ast
import pathlib

import pandas as pd
import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "helpers" / "portfolio_simulations.py"


def _ladder_keys(tree, method):
    """Every ``stop_config.get("<key>")`` under ``if sizing_method == "<method>":``."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        t = node.test
        if not (isinstance(t, ast.Compare)
                and isinstance(t.left, ast.Name) and t.left.id == "sizing_method"
                and len(t.ops) == 1 and isinstance(t.ops[0], ast.Eq)
                and isinstance(t.comparators[0], ast.Constant)
                and t.comparators[0].value == method):
            continue
        keys = set()
        for sub in ast.walk(node):
            if (isinstance(sub, ast.Call)
                    and isinstance(sub.func, ast.Attribute) and sub.func.attr == "get"
                    and isinstance(sub.func.value, ast.Name)
                    and sub.func.value.id == "stop_config"
                    and sub.args and isinstance(sub.args[0], ast.Constant)):
                keys.add(sub.args[0].value)
        return keys
    return None


def test_both_stop_distance_ladders_read_the_same_stop_config_keys():
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    frac = _ladder_keys(tree, "risk_parity")
    pts = _ladder_keys(tree, "risk_pct_capped")
    if frac is None or pts is None:
        pytest.skip("ladder shape changed -- see #391; retire this test with it")
    assert frac == pts, (
        "stop_config keys diverge between the two long-entry stop-distance "
        "ladders. Honoured only by risk_parity: %s. Only by risk_pct_capped: %s. "
        "One ladder is blind to a stop parameter the other honours; the sizer "
        "and the stop will disagree on every trade that sets it."
        % (sorted(frac - pts) or "none", sorted(pts - frac) or "none"))


def test_the_check_can_actually_fail():
    """The guard's own guard.

    A structural test that silently matches nothing is the failure mode this
    whole file exists to prevent, so the extractor is exercised against a source
    where the answer is known rather than trusted against the real one.
    """
    src = '''
def entry():
    if sizing_method == "risk_parity":
        a = stop_config.get("buffer", 0.0)
        b = stop_config.get("bars_back", 0)
    if sizing_method == "risk_pct_capped":
        c = stop_config.get("buffer", 0.0)
'''
    tree = ast.parse(src)
    assert _ladder_keys(tree, "risk_parity") == {"buffer", "bars_back"}
    assert _ladder_keys(tree, "risk_pct_capped") == {"buffer"}
    assert _ladder_keys(tree, "kelly") is None


# ---------------------------------------------------------------------------
class TestBufferIsHonouredByBothLadders:
    """The value half the structural check explicitly does not cover.

    `buffer` is the third parameter and the one currently held only by luck:
    hardcoding it to `0.0` in the points ladder passed **283 tests**.
    `test_sizing_honours_buffer` exists but is parameterised on the fraction
    ladder only — the same shape `bars_back` had before #390 added its pair.
    """

    @staticmethod
    def _shares(method, buffer):
        from unittest.mock import patch
        import helpers.portfolio_simulations as ps
        # Signal-bar Low = 90 against a ~100 fill. buffer 0.0 -> stop at 90;
        # buffer 0.10 -> stop at 81, so the distance roughly doubles and the
        # size roughly halves. Far enough apart that a dropped buffer cannot
        # look like rounding.
        rows = [("2024-01-02", 100, 105, 90, 100),
                ("2024-01-03", 100, 101, 99, 100),
                ("2024-01-04", 100, 101, 99, 100),
                ("2024-01-05", 100, 101, 99, 100)]
        idx = pd.to_datetime([r[0] for r in rows])
        df = pd.DataFrame(
            {"Open": [r[1] for r in rows], "High": [r[2] for r in rows],
             "Low": [r[3] for r in rows], "Close": [r[4] for r in rows],
             "Volume": [1_000_000] * len(rows)}, index=idx, dtype=float)
        df["ATR_14"] = 1.0
        cfg = {"position_sizing_method": method,
               "target_risk_per_trade": 0.02, "risk_pct_per_trade": 0.01,
               "max_contracts_cap": 20, "max_portfolio_heat": 1.0,
               "max_pct_adv": 0.0, "risk_pct_capped_max_notional_pct": 1.0}
        with patch.dict(ps.CONFIG, cfg):
            res = ps.run_portfolio_simulation(
                portfolio_data={"TEST": df},
                signals={"TEST": pd.Series([1, 0, 0, 0], index=df.index)},
                initial_capital=100_000.0, allocation_pct=1.0,
                spy_df=None, vix_df=None, tnx_df=None,
                stop_config={"type": "signal_bar", "buffer": buffer})
        if not res or not res.get("trade_log"):
            return None
        t = res["trade_log"][0]
        return float(t["Shares"]), float(t["InitialRisk"])

    @pytest.mark.parametrize("method", ["risk_parity", "risk_pct_capped"])
    def test_a_wider_buffer_sizes_smaller(self, method):
        tight = self._shares(method, 0.0)
        wide = self._shares(method, 0.10)
        if tight is None or wide is None:
            pytest.skip("no trade produced")
        # The buffer widens the stop, so InitialRisk must grow...
        assert wide[1] > tight[1] * 1.5, (method, tight, wide)
        # ...and the position must shrink in proportion. Hardcoding the buffer
        # to 0.0 leaves both pairs identical.
        assert wide[0] < tight[0] * 0.8, (
            "sizing ignored `buffer` for %s: %.4f shares at buffer 0.0 and "
            "%.4f at 0.10" % (method, tight[0], wide[0]))
