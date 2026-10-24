"""
Regression tests for issue #320 — equity-curve mark-to-market asymmetry when a
held symbol has no bar (or a NaN Close) on a date that exists in the overall
timeline (a sparse or mixed-calendar book).

- Longs: the missing-bar fallback used the last known Close WITHOUT a pd.notna
  guard, so a NaN last-known Close propagated NaN into total_equity for that
  date (later dropped by dropna(), silently shortening the return series).
- Shorts: there was NO fallback at all, so on a missing bar the short's
  unrealized P&L contributed 0 — portfolio equity spiked by the short's whole
  open P&L for that bar and back the next bar.

Both feed per-bar returns into Sharpe / rolling-Sharpe / drawdown, so the spikes
distort risk metrics. Fix: value both sides at the most recent non-NaN Close.
"""

import numpy as np
import pandas as pd
import pytest

import helpers.portfolio_simulations as ps
from helpers.portfolio_simulations import run_portfolio_simulation


def _patch(monkeypatch):
    monkeypatch.setitem(ps.CONFIG, "execution_time", "close")
    monkeypatch.setitem(ps.CONFIG, "slippage_pct", 0.0)
    monkeypatch.setitem(ps.CONFIG, "exclude_open_positions", False)
    monkeypatch.setitem(ps.CONFIG, "position_sizing_method", "fixed")
    monkeypatch.setitem(ps.CONFIG, "max_pct_adv", 0.0)
    monkeypatch.setitem(ps.CONFIG, "volume_impact_coeff", 0.0)


_ALL = pd.bdate_range("2024-01-01", periods=5)   # Mon..Fri (d0..d4)
D3 = _ALL[3]


def _ohlc(dates, closes):
    idx = pd.DatetimeIndex(dates)
    c = np.array(closes, dtype=float)
    return pd.DataFrame(
        {"Open": c, "High": c * 1.01, "Low": c * 0.99, "Close": c,
         "Volume": 1e6, "ATR_14": 1.0}, index=idx)


def test_short_missing_bar_does_not_spike_equity(monkeypatch):
    _patch(monkeypatch)
    # AAA drops d3; price falls so the short is in profit. BBB (flat) supplies d3
    # to the union timeline.
    aaa = _ohlc([_ALL[0], _ALL[1], _ALL[2], _ALL[4]], [100, 98, 96, 94])
    bbb = _ohlc(list(_ALL), [50, 50, 50, 50, 50])
    sa = pd.Series(0.0, index=aaa.index); sa.iloc[0] = -2.0   # short AAA at 100, held
    sb = pd.Series(0.0, index=bbb.index)
    res = run_portfolio_simulation(
        portfolio_data={"AAA": aaa, "BBB": bbb}, signals={"AAA": sa, "BBB": sb},
        initial_capital=100_000.0, allocation_pct=0.5,
        spy_df=None, vix_df=None, tnx_df=None, stop_config={"type": "none"})
    tl = res["portfolio_timeline"]
    assert not tl.isna().any(), "NaN in equity curve"
    # On d3 the short must be valued at its last-known close (d2=96), i.e. equity
    # equals the d2 equity — not the cash-only value the missing-bar bug produced.
    assert tl.loc[D3] == pytest.approx(tl.loc[_ALL[2]]), \
        "short MTM dropped to 0 on the missing bar (equity spike, #320)"


def test_long_nan_last_close_does_not_propagate_nan(monkeypatch):
    _patch(monkeypatch)
    # AAA's last bar before the missing d3 has a NaN Close (d2). The long
    # fallback must skip past it to the last NON-NaN close (d1=101), not
    # propagate NaN into total_equity.
    aaa = _ohlc([_ALL[0], _ALL[1], _ALL[2], _ALL[4]], [100, 101, np.nan, 103])
    bbb = _ohlc(list(_ALL), [50, 50, 50, 50, 50])
    sa = pd.Series(0.0, index=aaa.index); sa.iloc[0] = 1.0    # long AAA, held
    sb = pd.Series(0.0, index=bbb.index)
    res = run_portfolio_simulation(
        portfolio_data={"AAA": aaa, "BBB": bbb}, signals={"AAA": sa, "BBB": sb},
        initial_capital=100_000.0, allocation_pct=0.5,
        spy_df=None, vix_df=None, tnx_df=None, stop_config={"type": "none"})
    tl = res["portfolio_timeline"]
    assert not tl.isna().any(), "NaN in the equity curve (#320)"
    # Under the bug d3's equity became NaN and was dropped, silently shortening
    # the return series. The fix keeps d3 valued at the last non-NaN close.
    assert D3 in tl.index, "missing bar dropped from the equity curve (#320)"
    # Value pin: d2 (present-but-NaN) and d3 (missing) are both valued at the
    # last non-NaN close (d1=101), i.e. equal to the d1 equity — not 0 and not NaN.
    assert tl.loc[D3] == pytest.approx(tl.loc[_ALL[1]])
    assert tl.loc[_ALL[2]] == pytest.approx(tl.loc[_ALL[1]])


def test_eob_mtm_logs_trade_when_holder_misses_the_last_date(monkeypatch):
    _patch(monkeypatch)
    # AAA (holds a long) has no bar on the union's last date d4; BBB supplies it.
    # The end-of-backtest MTM must still log AAA's open trade (valued at its last
    # known close), matching the equity curve — the old code skipped it.
    aaa = _ohlc([_ALL[0], _ALL[1], _ALL[2], _ALL[3]], [100, 101, 102, 103])
    bbb = _ohlc(list(_ALL), [50, 50, 50, 50, 50])
    sa = pd.Series(0.0, index=aaa.index); sa.iloc[0] = 1.0
    sb = pd.Series(0.0, index=bbb.index)
    res = run_portfolio_simulation(
        portfolio_data={"AAA": aaa, "BBB": bbb}, signals={"AAA": sa, "BBB": sb},
        initial_capital=100_000.0, allocation_pct=0.5,
        spy_df=None, vix_df=None, tnx_df=None, stop_config={"type": "none"})
    trades = res["trade_log"] if res else []
    assert any(t["Symbol"] == "AAA" and t["ExitReason"] == "End of Backtest"
               for t in trades), "open trade not logged when holder misses the last bar (#320)"
