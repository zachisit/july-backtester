# tests/test_score_priority_500.py
"""
Issue #500: score-based entry priority, per-bar new-position / new-risk limits,
the entry-candidate audit log, shadow returns, and the look-ahead guard.
"""

import os
import sys
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from helpers.portfolio_simulations import run_portfolio_simulation  # noqa: E402

BASE_CFG = {
    "slippage_pct": 0.0, "commission_per_share": 0.0, "execution_time": "open",
    "risk_free_rate": 0.0, "htb_rate_annual": 0.0, "volume_impact_coeff": 0.0,
    "max_pct_adv": 0.0, "position_sizing_method": "fixed",
    "target_risk_per_trade": 0.02, "max_portfolio_heat": 1.0,
    "entry_priority": "score", "entry_score_ascending": False,
    "max_new_positions_per_bar": None, "max_new_risk_per_bar": None,
    "log_entry_candidates": True, "shadow_skipped_candidates": False,
    "exclude_open_positions": False, "include_delisted": False,
    "intrabar_resolution": False, "time_stop": None,
    "gap_below_stop_on_entry": "skip",
    "instruments": {"default_asset_class": "equity", "overrides": {}},
}
PCT = {"type": "percentage", "value": 0.05}


def _frame(n=6, px=100.0, drift=0.0):
    idx = pd.bdate_range("2024-01-02", periods=n)
    idx.name = "Datetime"
    c = px * (1 + drift) ** np.arange(n)
    return pd.DataFrame({"Open": c, "High": c * 1.01, "Low": c * 0.99, "Close": c,
                         "Volume": 1e6}, index=idx)


def _book(scores, n=6, sig_bar=0, drifts=None):
    """One symbol per score, all signalling on bar `sig_bar` (fill on sig_bar+1)."""
    data, sigs, aux = {}, {}, {}
    for k, (sym, sc) in enumerate(scores.items()):
        df = _frame(n, drift=(drifts or {}).get(sym, 0.0))
        data[sym] = df
        s = pd.Series(0.0, index=df.index)
        s.iloc[sig_bar] = 1
        sigs[sym] = s
        a = pd.DataFrame({"entry_score": np.nan}, index=df.index)
        a.iloc[sig_bar, 0] = sc
        aux[sym] = a
    return data, sigs, aux


def _run(data, sigs, aux, cfg_over=None, stop=PCT, alloc=0.30, capital=100_000.0):
    cfg = {**BASE_CFG, **(cfg_over or {})}
    with patch.dict("config.CONFIG", cfg, clear=False):
        return run_portfolio_simulation(
            portfolio_data=data, signals=sigs, initial_capital=capital,
            allocation_pct=alloc, spy_df=None, vix_df=None, tnx_df=None,
            stop_config=stop, signal_aux=aux)


def _taken(res):
    return sorted({t["Symbol"] for t in res["trade_log"]})


SCORES10 = {f"S{i:02d}": float(s) for i, s in
            enumerate([5, 9, 1, 7, 3, 10, 2, 8, 6, 4])}   # top-3: S05(10), S01(9), S07(8)


class TestOverCapacity:
    def test_top3_scores_taken(self):
        # 34% each: two full positions, the third is cash-clamped to the
        # remaining 32%, the fourth finds no cash.
        res = _run(*_book(SCORES10), alloc=0.34)
        assert _taken(res) == ["S01", "S05", "S07"]

    def test_deterministic(self):
        a = _run(*_book(SCORES10))
        b = _run(*_book(SCORES10))
        assert a["trade_log"] == b["trade_log"]

    def test_alphabetical_would_differ(self):
        res = _run(*_book(SCORES10), {"entry_priority": "alphabetical"}, alloc=0.34)
        assert _taken(res) == ["S00", "S01", "S02"]

    def test_ascending(self):
        res = _run(*_book(SCORES10), {"entry_score_ascending": True}, alloc=0.34)
        assert _taken(res) == ["S02", "S04", "S06"]                # scores 1, 2, 3

    def test_max_new_positions_per_bar(self):
        res = _run(*_book(SCORES10), {"max_new_positions_per_bar": 2}, alloc=0.05)
        assert _taken(res) == ["S01", "S05"]


class TestTies:
    def test_ties_alphabetical(self):
        res = _run(*_book({"ZZZ": 5.0, "MMM": 5.0, "AAA": 5.0, "BBB": 1.0}), alloc=0.50)
        assert _taken(res) == ["AAA", "MMM"]

    def test_nan_score_goes_last(self):
        res = _run(*_book({"AAA": np.nan, "BBB": 1.0, "CCC": 2.0}), alloc=0.50)
        assert _taken(res) == ["BBB", "CCC"]


class TestRiskCap:
    def test_high_risk_candidate_skipped_next_fits(self):
        # Equal 10% positions; per-name stop distance differs. Risk per entry =
        # 10k * stop%. Cap 0.012 * 100k = 1200 of new risk per bar.
        data, sigs, aux = _book({"AAA": 3.0, "BBB": 2.0, "CCC": 1.0})
        stops = {"AAA": 0.10, "BBB": 0.02, "CCC": 0.08}      # risk 1000 / 200 / 800
        # one stop config cannot vary per symbol, so use signal_bar lows instead
        for sym, d in stops.items():
            data[sym].iloc[0, data[sym].columns.get_loc("Low")] = 100 * (1 - d)
        res = _run(data, sigs, aux, {"max_new_risk_per_bar": 0.012}, alloc=0.10,
                   stop={"type": "signal_bar", "buffer": 0.0})
        assert _taken(res) == ["AAA", "BBB"]                 # 1000 + 200; CCC (800) would exceed
        cand = pd.DataFrame(res["entry_candidates"])
        assert cand.set_index("Symbol").loc["CCC", "skipped_reason"] == "bar_risk"

    def test_loop_does_not_stop_at_first_failure(self):
        data, sigs, aux = _book({"AAA": 3.0, "BBB": 2.0, "CCC": 1.0})
        for sym, d in {"AAA": 0.02, "BBB": 0.10, "CCC": 0.02}.items():
            data[sym].iloc[0, data[sym].columns.get_loc("Low")] = 100 * (1 - d)
        res = _run(data, sigs, aux, {"max_new_risk_per_bar": 0.005}, alloc=0.10,
                   stop={"type": "signal_bar", "buffer": 0.0})
        assert _taken(res) == ["AAA", "CCC"]                 # BBB (1000) skipped, CCC fits


class TestNoScore:
    def test_missing_score_column_fails_loudly(self):
        data, sigs, _ = _book({"AAA": 1.0})
        with pytest.raises(ValueError, match="entry_score"):
            _run(data, sigs, None)
        with pytest.raises(ValueError, match="entry_score"):
            _run(data, sigs, {"AAA": pd.DataFrame({"raw_low": 1.0}, index=data["AAA"].index)})


class TestCandidateLog:
    def test_log_records_score_taken_and_reason(self):
        res = _run(*_book(SCORES10), {"max_new_positions_per_bar": 3}, alloc=0.05)
        cand = pd.DataFrame(res["entry_candidates"])
        assert len(cand) == 10
        assert cand["Taken"].sum() == 3
        assert set(cand.loc[~cand["Taken"], "skipped_reason"]) == {"bar_count"}
        assert cand.set_index("Symbol").loc["S05", "Score"] == 10.0
        tl = pd.DataFrame(res["trade_log"])
        assert set(tl["EntryScore"]) == {10.0, 9.0, 8.0}

    def test_cash_skip_logged(self):
        res = _run(*_book(SCORES10), alloc=0.34)
        cand = pd.DataFrame(res["entry_candidates"])
        assert (cand.loc[~cand["Taken"], "skipped_reason"] == "cash").all()

    def test_duplicate_symbol_logged(self):
        df = _frame(8)
        s = pd.Series(0.0, index=df.index)
        s.iloc[0] = 1
        s.iloc[2] = 0
        s.iloc[3] = 1           # second edge while still holding
        aux = pd.DataFrame({"entry_score": 1.0}, index=df.index)
        res = _run({"AAA": df}, {"AAA": s}, {"AAA": aux})
        cand = pd.DataFrame(res["entry_candidates"])
        assert "duplicate_symbol" in set(cand["skipped_reason"].dropna())

    def test_log_off_by_default_key(self):
        res = _run(*_book(SCORES10), {"log_entry_candidates": False})
        assert "entry_candidates" not in res


class TestShadow:
    def test_skipped_candidates_get_shadow_returns(self):
        drifts = {s: 0.01 * (i - 5) for i, s in enumerate(SCORES10)}
        res = _run(*_book(SCORES10, n=10, drifts=drifts),
                   {"max_new_positions_per_bar": 3, "shadow_skipped_candidates": True},
                   alloc=0.05, stop={"type": "none"})
        cand = pd.DataFrame(res["entry_candidates"])
        skipped = cand[~cand["Taken"]]
        assert skipped["ShadowReturnPct"].notna().all()
        # Same exit simulation: a taken name's shadow, if re-run, equals its real trade.
        # Check one skipped name against an unconstrained run of the same book.
        free = _run(*_book(SCORES10, n=10, drifts=drifts), {"log_entry_candidates": False},
                    alloc=0.05, stop={"type": "none"})
        real = {t["Symbol"]: t["ProfitPct"] for t in free["trade_log"]}
        for _, r in skipped.iterrows():
            assert r["ShadowReturnPct"] == pytest.approx(real[r["Symbol"]], rel=1e-9, abs=1e-12)


class TestLookAheadGuard:
    def test_score_after_signal_bar_does_not_change_anything(self):
        data, sigs, aux = _book(SCORES10, n=8)
        base = _run(data, sigs, aux, {"max_new_positions_per_bar": 3}, alloc=0.05)
        rng = np.random.default_rng(0)
        aux2 = {}
        for sym, a in aux.items():
            b = a.copy()
            b.iloc[1:, 0] = rng.normal(0, 100, len(b) - 1)    # everything AFTER the signal bar
            aux2[sym] = b
        pert = _run(data, sigs, aux2, {"max_new_positions_per_bar": 3}, alloc=0.05)
        assert base["trade_log"] == pert["trade_log"]

    def test_score_on_signal_bar_does_change_selection(self):
        data, sigs, aux = _book(SCORES10, n=8)
        aux["S02"].iloc[0, 0] = 99.0
        res = _run(data, sigs, aux, {"max_new_positions_per_bar": 3}, alloc=0.05)
        assert "S02" in _taken(res)


# ---------------------------------------------------------------------------
# Adversarial-QA regressions (#504 review)
def _f(rows):
    idx = pd.bdate_range("2024-01-02", periods=len(rows))
    idx.name = "Datetime"
    o, h, l, c = zip(*rows)
    return pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": c, "Volume": 1e6},
                        index=idx, dtype=float)


def _sig(df, pairs):
    s = pd.Series(0.0, index=df.index)
    for i, v in pairs.items():
        s.iloc[i] = v
    return s


class TestQARegressions:
    def test_shadow_keeps_minus2_as_a_long_exit(self):
        n = 30
        data = {"AAA": _f([(100, 101, 99, 100)] * n),
                "BBB": _f([(100 + i, 101 + i, 99 + i, 100 + i) for i in range(n)])}
        sigs = {"AAA": _sig(data["AAA"], {3: 1}), "BBB": _sig(data["BBB"], {3: 1, 8: -2})}
        aux = {k: pd.DataFrame({"entry_score": 1.0}, index=d.index) for k, d in data.items()}
        r = _run(data, sigs, aux, {"max_new_positions_per_bar": 1, "shadow_skipped_candidates": True},
                 stop={"type": "none"}, alloc=0.10)
        cand = [c for c in r["entry_candidates"] if c["Symbol"] == "BBB" and c["Side"] == "long"][0]
        free = _run(data, sigs, aux, {"log_entry_candidates": False}, stop={"type": "none"}, alloc=0.10)
        real = [t for t in free["trade_log"] if t["Symbol"] == "BBB"][0]
        assert cand["ShadowExitDate"] == real["ExitDate"]
        assert cand["ShadowReturnPct"] == pytest.approx(real["ProfitPct"])

    @pytest.mark.parametrize("label", ["Score", " SCORE ", "score"])
    def test_priority_value_is_normalised(self, label):
        res = _run(*_book({"AAA": 1.0, "BBB": 2.0, "CCC": 3.0}),
                   {"entry_priority": label, "max_new_positions_per_bar": 1}, alloc=0.10)
        assert _taken(res) == ["CCC"]

    def test_short_heat_rejection_is_logged(self):
        n = 10
        data = {"AAA": _f([(100, 101, 99, 100)] * n), "ZZZ": _f([(100, 101, 99, 100)] * n)}
        sigs = {"AAA": _sig(data["AAA"], {3: -2}), "ZZZ": _sig(data["ZZZ"], {2: 1})}
        aux = {k: pd.DataFrame({"entry_score": 1.0}, index=d.index) for k, d in data.items()}
        r = _run(data, sigs, aux, {"max_portfolio_heat": 0.006, "target_risk_per_trade": 0.05},
                 alloc=0.10)
        rows = [(c["Side"], c["Taken"], c["skipped_reason"]) for c in r["entry_candidates"]
                if c["Symbol"] == "AAA"]
        assert rows == [("short", False, "heat")]

    def test_zero_size_is_not_labelled_cash(self):
        n = 10
        rows = [(100, 101, 99, 100)] * n
        rows[4] = (95, 96, 94, 95)                 # opens below the bar-3 low -> no stop distance
        data = {"AAA": _f(rows), "ZZZ": _f([(100, 101, 99, 100)] * n)}
        sigs = {"AAA": _sig(data["AAA"], {3: 1}), "ZZZ": _sig(data["ZZZ"], {2: 1})}
        aux = {k: pd.DataFrame({"entry_score": 1.0}, index=d.index) for k, d in data.items()}
        r = _run(data, sigs, aux, {"position_sizing_method": "fixed_risk", "risk_per_trade": 0.005,
                                   "max_position_pct": 0.05, "gap_below_stop_on_entry": "ignore"},
                 stop={"type": "signal_bar_low", "offset": 0.01}, alloc=0.10)
        rows = [c["skipped_reason"] for c in r["entry_candidates"] if c["Symbol"] == "AAA"]
        assert rows == ["zero_size"]


class TestQARound2:
    def test_equity_short_zero_size_label(self):
        n = 10
        rows = [(100, 101, 99, 100)] * n
        data = {"AAA": _f(rows), "ZZZ": _f(rows)}
        sigs = {"AAA": _sig(data["AAA"], {3: -2}), "ZZZ": _sig(data["ZZZ"], {2: 1})}
        aux = {k: pd.DataFrame({"entry_score": 1.0}, index=d.index) for k, d in data.items()}
        r = _run(data, sigs, aux, {"position_sizing_method": "fixed_risk", "risk_per_trade": 0.005,
                                   "max_position_pct": 0.05},
                 stop={"type": "signal_bar_low", "offset": 0.01}, alloc=0.10)
        rows = [c["skipped_reason"] for c in r["entry_candidates"] if c["Symbol"] == "AAA"]
        assert rows == ["zero_size"]

    def test_zero_trade_run_still_reports_candidates(self, caplog):
        import logging
        n = 8
        data = {"AAA": _f([(100, 101, 99, 100)] * n)}
        sigs = {"AAA": _sig(data["AAA"], {2: 1})}
        aux = {"AAA": pd.DataFrame({"entry_score": 1.0}, index=data["AAA"].index)}
        with caplog.at_level(logging.WARNING, logger="helpers.portfolio_simulations"):
            r = _run(data, sigs, aux, {"max_new_positions_per_bar": 0})
        assert r is None
        assert "No trades: 1 entry candidates" in caplog.text and "bar_count=1" in caplog.text

    def test_futures_long_cut_below_one_contract_by_adv_is_labelled_adv(self):
        n = 8
        data = {"MESM6": _f([(5000, 5010, 4990, 5000)] * n), "AAA": _f([(100, 101, 99, 100)] * n)}
        sigs = {"MESM6": _sig(data["MESM6"], {2: 1}), "AAA": _sig(data["AAA"], {2: 1})}
        aux = {k: pd.DataFrame({"entry_score": 1.0}, index=d.index) for k, d in data.items()}
        inst = {"default_asset_class": "equity", "overrides": {},
                "futures_initial_margin_pct": 0.10, "futures_commission_per_contract": 0.0,
                "futures_slippage_ticks": 0.0}
        r = _run(data, sigs, aux, {"instruments": inst, "max_pct_adv": 1e-7}, alloc=0.10)
        mes = [c["skipped_reason"] for c in r["entry_candidates"] if c["Symbol"] == "MESM6"]
        assert mes == ["adv"]
