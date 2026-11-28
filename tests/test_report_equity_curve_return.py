"""tests/test_report_equity_curve_return.py -- #519.

The report's headline Net P&L / Total Return / CAGR (and everything derived
from them: Calmar, after-tax CAGR, Return/DD, Recovery Factor) used
``initial_equity + sum(trade Profit)`` while drawdown, Sharpe and the charts
used the run's equity curve (``PORTFOLIO_TIMELINE``). Any equity change that is
not booked into a trade's Profit -- cash interest on idle cash (#518), fees or
borrow booked to cash, open MTM on a realised-only log, end-of-run marking --
made the headline disagree with the curve it is printed next to.

With a usable curve the headline now comes from the curve end vs the starting
capital the report resolved, and the non-trade part is printed. Without a curve
nothing changes. Synthetic data only, no network.
"""
from __future__ import annotations

import json
import os
import re

import matplotlib
matplotlib.use("Agg")
import numpy as np
import pandas as pd
import pytest

from trade_analyzer import analyzer, calculations, data_handler, report_generator

INIT = 100_000.0
RF = 0.05
TD = 252
_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "engine_golden_master.json")


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

def _trades(n: int = 40, seed: int = 7, start="2019-01-02") -> pd.DataFrame:
    """Analyzer-format trades (as summary.py writes them), alternating wins/losses."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start, periods=n * 10)
    rows = []
    for i in range(n):
        entry, exit_ = dates[i * 10 + 1], dates[i * 10 + 6]
        profit = float(round(rng.normal(150.0, 600.0), 2))
        rows.append({
            "Symbol": "AAA", "Date": entry, "Ex. date": exit_,
            "Price": 100.0, "Ex. Price": 100.0 + profit / 100.0,
            "Profit": profit, "% Profit": profit / 10_000.0 * 100.0,
            "Shares": 100.0, "Win": int(profit > 0), "# bars": 5.0,
            "MAE": -1.0, "MFE": 1.0,
        })
    return pd.DataFrame(rows)


def _timeline(trades: pd.DataFrame, non_trade_total: float = 0.0) -> pd.Series:
    """Daily curve: INIT + cumulative realised Profit, plus a non-trade amount
    accruing linearly over the whole period (stands in for cash interest)."""
    idx = pd.bdate_range(trades["Date"].min() - pd.Timedelta(days=30),
                         trades["Ex. date"].max() + pd.Timedelta(days=3))
    realised = trades.groupby("Ex. date")["Profit"].sum().reindex(idx, fill_value=0.0).cumsum()
    accrual = pd.Series(np.linspace(0.0, non_trade_total, len(idx)), index=idx)
    return (INIT + realised + accrual).rename("Equity")


def _summary(trades, curve, *, pass_curve=True):
    cleaned, _ = data_handler.clean_trades_data(trades.copy(), INIT)
    returns = curve.pct_change().dropna()
    kwargs = {"portfolio_timeline": curve if pass_curve else None}
    _, text = report_generator.generate_overall_metrics_summary(
        cleaned, returns, pd.Series(dtype=float), None, curve,
        "SPY", INIT, RF, TD, **kwargs)
    return text


def _line(text: str, label: str) -> str | None:
    for ln in text.splitlines():
        if ln.startswith(label):
            return ln[len(label):].strip()
    return None


def _money(s: str) -> float:
    return float(s.replace("$", "").replace(",", ""))


def _pct(s: str) -> float:
    return float(s.replace("%", "")) / 100.0


def _curve_cagr(curve):
    years = (curve.index[-1] - curve.index[0]).days / 365.25
    return (curve.iloc[-1] / INIT) ** (1 / years) - 1


# ---------------------------------------------------------------------------
# resolve_headline_pnl
# ---------------------------------------------------------------------------

class TestResolveHeadlinePnl:
    def test_curve_end_is_headline(self):
        curve = pd.Series([INIT, 101_000.0, 108_000.0],
                          index=pd.bdate_range("2020-01-01", periods=3))
        h = calculations.resolve_headline_pnl(5_000.0, INIT, curve)
        assert h["source"] == "equity_curve"
        assert h["net_profit"] == pytest.approx(8_000.0)
        assert h["final_equity"] == pytest.approx(108_000.0)
        assert h["trade_profit"] == pytest.approx(5_000.0)
        assert h["non_trade_pnl"] == pytest.approx(3_000.0)

    def test_no_curve_is_trade_log_and_never_invents_a_gap(self):
        h = calculations.resolve_headline_pnl(5_000.0, INIT, None)
        assert h["source"] == "trade_log"
        assert h["net_profit"] == 5_000.0
        assert h["final_equity"] == INIT + 5_000.0
        assert h["non_trade_pnl"] is None

    def test_unusable_curve_falls_back(self):
        curve = pd.Series([np.nan, np.nan], index=pd.bdate_range("2020-01-01", periods=2))
        assert calculations.resolve_headline_pnl(5.0, INIT, curve)["source"] == "trade_log"
        assert calculations.resolve_headline_pnl(5.0, INIT, pd.Series(dtype=float))["source"] == "trade_log"

    def test_trailing_nan_uses_last_finite_point(self):
        curve = pd.Series([INIT, 104_000.0, np.nan], index=pd.bdate_range("2020-01-01", periods=3))
        assert calculations.resolve_headline_pnl(0.0, INIT, curve)["net_profit"] == pytest.approx(4_000.0)

    def test_materiality(self):
        assert not calculations.non_trade_pnl_is_material(None, INIT)
        assert not calculations.non_trade_pnl_is_material(1e-6, INIT)
        assert calculations.non_trade_pnl_is_material(5.43, INIT)
        assert calculations.non_trade_pnl_is_material(-7_738.0, INIT)


# ---------------------------------------------------------------------------
# Text report (also the classic layout's metrics appendix + console key metrics)
# ---------------------------------------------------------------------------

class TestOverallSummaryText:
    def test_non_trade_gain_moves_headline_to_curve(self):
        trades = _trades()
        curve = _timeline(trades, non_trade_total=7_738.0)
        text = _summary(trades, curve)

        curve_net = curve.iloc[-1] - INIT
        trade_net = trades["Profit"].sum()
        assert _money(_line(text, "Total Net Profit:")) == pytest.approx(curve_net, abs=0.01)
        assert _pct(_line(text, "Strategy Total Return:")) == pytest.approx(curve_net / INIT, abs=1e-4)
        assert _pct(_line(text, "CAGR:")) == pytest.approx(_curve_cagr(curve), abs=1e-4)
        # the gap line names the trade-log figure and the difference
        assert _money(_line(text, "Net Profit from Trade Log:")) == pytest.approx(trade_net, abs=0.01)
        assert _money(_line(text, "Equity Change Not in Trade Log:")) == pytest.approx(7_738.0, abs=0.01)
        # derived: after-tax CAGR taxes the curve's profit; Calmar uses the curve CAGR
        years = (curve.index[-1] - curve.index[0]).days / 365.25
        at = (1 + curve_net * 0.70 / INIT) ** (1 / years) - 1
        assert _pct(_line(text, "Estimated After-Tax CAGR (30% tax):")) == pytest.approx(at, abs=1e-4)
        _, _, _, mdd = calculations.calculate_equity_drawdown(curve)
        calmar = _curve_cagr(curve) / (mdd / 100.0)
        assert float(_line(text, "Calmar Ratio (CAGR / Max Equity DD%):")) == pytest.approx(calmar, abs=0.01)

    def test_no_curve_text_is_unchanged(self):
        """portfolio_timeline=None: headline = sum(Profit), no gap line."""
        trades = _trades()
        curve = _timeline(trades, non_trade_total=7_738.0)
        text = _summary(trades, curve, pass_curve=False)
        assert _money(_line(text, "Total Net Profit:")) == pytest.approx(trades["Profit"].sum(), abs=0.01)
        assert _line(text, "Equity Change Not in Trade Log:") is None
        assert _line(text, "Net Profit from Trade Log:") is None
        legacy_final = INIT + trades["Profit"].sum()
        years = (curve.index[-1] - curve.index[0]).days / 365.25
        assert _pct(_line(text, "CAGR:")) == pytest.approx(
            (legacy_final / INIT) ** (1 / years) - 1, abs=1e-4)


# ---------------------------------------------------------------------------
# Reconciling engine runs: numbers do not move
# ---------------------------------------------------------------------------

def _golden():
    with open(_FIXTURE) as fh:
        return json.load(fh)


def _golden_case(snap):
    log = pd.DataFrame(snap["trade_log"])
    trades = pd.DataFrame({
        "Date": pd.to_datetime(log["EntryDate"]),
        "Ex. date": pd.to_datetime(log["ExitDate"]),
        "Profit": log["Profit"].astype(float),
        "% Profit": log["ProfitPct"].astype(float) * 100.0,
        "Win": log["is_win"].astype(int),
    })
    eq = snap["equity_curve"]
    # The fixture stores curve values only; any index of the right length works
    # because both calls below read the same curve for duration.
    curve = pd.Series(eq, index=pd.bdate_range("2023-01-02", periods=len(eq)), dtype=float)
    return trades, curve


_HEADLINE_LABELS = ("Total Net Profit:", "Strategy Total Return:", "CAGR:",
                    "Estimated After-Tax CAGR (30% tax):",
                    "Calmar Ratio (CAGR / Max Equity DD%):")


def _reconciling_names():
    out = []
    for name, snap in _golden().items():
        gap = snap["equity_curve"][-1] - INIT - sum(t["Profit"] for t in snap["trade_log"])
        if abs(gap) < 1e-3 and len(snap["trade_log"]) >= 2:
            out.append(name)
    return out


class TestReconcilingEngineRunsUnchanged:
    @pytest.mark.parametrize("name", _reconciling_names())
    def test_headline_identical_to_trade_log_basis(self, name):
        """Golden-master engine runs whose curve end == INIT + sum(Profit):
        curve-based and trade-based headlines print the same strings."""
        trades, curve = _golden_case(_golden()[name])
        with_curve = _summary(trades, curve, pass_curve=True)
        trade_basis = _summary(trades, curve, pass_curve=False)
        for label in _HEADLINE_LABELS:
            assert _line(with_curve, label) == _line(trade_basis, label), (name, label)
        assert _line(with_curve, "Equity Change Not in Trade Log:") is None

    def test_there_are_reconciling_cases(self):
        assert len(_reconciling_names()) >= 3

    def test_end_of_backtest_marking_gap_is_disclosed(self):
        """long_basic: the curve's last point is the MTM mark (what the terminal's
        pnl_percent uses); the End-of-Backtest close in the log carries exit
        costs. The headline follows the curve and the difference is printed."""
        snap = _golden()["long_basic"]
        trades, curve = _golden_case(snap)
        text = _summary(trades, curve)
        assert _pct(_line(text, "Strategy Total Return:")) == pytest.approx(
            snap["scalars"]["pnl_percent"], abs=1e-4)
        gap = curve.iloc[-1] - INIT - trades["Profit"].sum()
        assert _money(_line(text, "Equity Change Not in Trade Log:")) == pytest.approx(gap, abs=0.01)

    def test_realised_only_log_reports_curve_and_names_open_mtm(self):
        """exclude_open: the trade log omits the open position, the curve keeps
        its MTM. The report follows the curve (the account's equity) and shows
        the open MTM as the non-trade line; the terminal's realised-only
        pnl_percent is the trade-log figure on that line."""
        snap = _golden()["exclude_open"]
        trades, curve = _golden_case(snap)
        text = _summary(trades, curve)
        assert _money(_line(text, "Total Net Profit:")) == pytest.approx(curve.iloc[-1] - INIT, abs=0.01)
        assert _money(_line(text, "Net Profit from Trade Log:")) / INIT == pytest.approx(
            snap["scalars"]["pnl_percent"], abs=1e-6)
        assert _money(_line(text, "Equity Change Not in Trade Log:")) == pytest.approx(
            curve.iloc[-1] - INIT - trades["Profit"].sum(), abs=0.01)


# ---------------------------------------------------------------------------
# End to end through the analyzer, both PDF layouts
# ---------------------------------------------------------------------------

def _run_report(tmp_path, monkeypatch, trades, curve, layout):
    monkeypatch.setattr(data_handler, "download_benchmark_data", lambda *a, **k: None)
    monkeypatch.setattr(report_generator, "generate_markdown_report", lambda *a, **k: None)
    cfg = {"INITIAL_EQUITY": INIT, "RISK_FREE_RATE": RF, "TRADING_DAYS_PER_YEAR": TD,
           "MC_SIMULATIONS": 20, "LAYOUT": layout, "WFA_SPLIT_RATIO": None}
    if curve is not None:
        cfg["PORTFOLIO_TIMELINE"] = curve
    analyzer.generate_trade_report(trades.copy(), str(tmp_path / "reports"), "Strat", cfg)


def _fig_text(fig) -> str:
    texts = [t.get_text() for t in fig.texts]
    for ax in fig.axes:
        texts += [t.get_text() for t in ax.texts]
    return "\n".join(texts)


class TestV3Layout:
    def _capture(self, monkeypatch):
        from trade_analyzer import _pdf_v3
        seen = {}
        orig = _pdf_v3.build_v3_page1

        def _spy(meta, M):
            fig = orig(meta, M)
            seen["M"], seen["text"], seen["meta"] = dict(M), _fig_text(fig), dict(meta)
            return fig
        monkeypatch.setattr(_pdf_v3, "build_v3_page1", _spy)
        return seen

    def test_headline_from_curve_and_gap_shown(self, tmp_path, monkeypatch):
        trades = _trades()
        curve = _timeline(trades, non_trade_total=7_738.0)
        seen = self._capture(monkeypatch)
        _run_report(tmp_path, monkeypatch, trades, curve, "v3")
        M = seen["M"]
        curve_net = curve.iloc[-1] - INIT
        assert M["total_profit"] == pytest.approx(curve_net, abs=1e-6)
        assert M["cagr"] == pytest.approx(_curve_cagr(curve), abs=1e-9)
        assert M["trade_profit"] == pytest.approx(trades["Profit"].sum(), abs=1e-6)
        assert M["non_trade_pnl"] == pytest.approx(7_738.0, abs=1e-6)
        mdd = float((curve.cummax() - curve).max())
        assert M["ret_dd"] == pytest.approx(curve_net / mdd, rel=1e-9)
        assert M["recovery_factor"] == pytest.approx(curve_net / mdd, rel=1e-9)
        assert "Not in Trade Log" in seen["text"]
        assert "not in trades" in seen["text"]
        # header period = the span Net P&L / duration are measured over
        assert seen["meta"]["start_date"] == curve.index[0].strftime("%d %b %Y")
        assert seen["meta"]["end_date"] == curve.index[-1].strftime("%d %b %Y")

    def test_no_curve_unchanged(self, tmp_path, monkeypatch):
        trades = _trades()
        seen = self._capture(monkeypatch)
        _run_report(tmp_path, monkeypatch, trades, None, "v3")
        M = seen["M"]
        assert M["total_profit"] == pytest.approx(trades["Profit"].sum(), abs=1e-6)
        assert M["non_trade_pnl"] is None
        assert "Not in Trade Log" not in seen["text"]
        assert seen["meta"]["start_date"] == trades["Date"].min().strftime("%d %b %Y")
        assert seen["meta"]["end_date"] == trades["Ex. date"].max().strftime("%d %b %Y")


class TestClassicLayout:
    def _capture(self, monkeypatch):
        from trade_analyzer import _pdf_pages
        seen = {}
        orig_cover = _pdf_pages.build_cover_page
        orig_exec = _pdf_pages.build_executive_summary_page

        def _cover(meta):
            seen["cover"] = dict(meta)
            return orig_cover(meta)

        def _exec(*args, **kwargs):
            fig = orig_exec(*args, **kwargs)
            seen["exec_text"] = _fig_text(fig)
            return fig
        monkeypatch.setattr(_pdf_pages, "build_cover_page", _cover)
        monkeypatch.setattr(_pdf_pages, "build_executive_summary_page", _exec)
        return seen

    def test_cover_and_exec_summary_from_curve(self, tmp_path, monkeypatch):
        trades = _trades()
        curve = _timeline(trades, non_trade_total=7_738.0)
        seen = self._capture(monkeypatch)
        _run_report(tmp_path, monkeypatch, trades, curve, "classic")
        curve_net = curve.iloc[-1] - INIT
        assert seen["cover"]["total_return"] == pytest.approx(curve_net / INIT, abs=1e-9)
        # cover CAGR uses the curve's span, the same as the executive summary
        assert seen["cover"]["cagr"] == pytest.approx(_curve_cagr(curve), abs=1e-9)
        assert f"${curve_net:,.0f}" in seen["exec_text"] or f"${curve_net:,.2f}" in seen["exec_text"]
        assert "not in trades" in seen["exec_text"]

    def test_cover_period_is_the_curve_span(self, tmp_path, monkeypatch):
        """Codex r1: the cover's 'Backtest period' must be the span its CAGR is
        measured over (the curve's), not first entry -> last exit."""
        trades = _trades()
        curve = _timeline(trades, non_trade_total=7_738.0)
        assert curve.index[0] < trades["Date"].min()  # curve starts before trading
        seen = self._capture(monkeypatch)
        _run_report(tmp_path, monkeypatch, trades, curve, "classic")
        assert seen["cover"]["start_date"] == curve.index[0].strftime("%Y-%m-%d")
        assert seen["cover"]["end_date"] == curve.index[-1].strftime("%Y-%m-%d")

    def test_no_curve_cover_unchanged(self, tmp_path, monkeypatch):
        trades = _trades()
        seen = self._capture(monkeypatch)
        _run_report(tmp_path, monkeypatch, trades, None, "classic")
        net = trades["Profit"].sum()
        years = (trades["Ex. date"].max() - trades["Date"].min()).days / 365.25
        assert seen["cover"]["total_return"] == pytest.approx(net / INIT, abs=1e-9)
        assert seen["cover"]["cagr"] == pytest.approx((1 + net / INIT) ** (1 / years) - 1, abs=1e-9)
        assert "not in trades" not in seen["exec_text"]
