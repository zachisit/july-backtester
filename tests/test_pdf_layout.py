"""
tests/test_pdf_layout.py  — smoke tests for the new PDF tearsheet (#115)

All tests use a small synthetic trades_df so there is no network or file I/O
dependency beyond the tmp_path fixture.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path

import matplotlib
matplotlib.use('Agg')   # headless; must be set before any pyplot import
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_trades(n: int = 30) -> pd.DataFrame:
    """Build a minimal synthetic trades DataFrame with all optional columns."""
    rng = np.random.default_rng(42)
    start = datetime(2020, 1, 2)
    rows = []
    eq = 50_000.0
    for i in range(n):
        entry = start + timedelta(days=i * 3)
        exit_ = entry + timedelta(days=int(rng.integers(2, 15)))
        profit = float(rng.uniform(-500, 1500))
        eq += profit
        pct = profit / 50_000 * 100
        rows.append({
            'Symbol':    rng.choice(['AAPL', 'MSFT', 'GOOG', 'AMZN', 'TSLA']),
            'Date':      entry,
            'Ex. date':  exit_,
            'Price':     float(rng.uniform(50, 300)),
            'Ex. Price': float(rng.uniform(50, 300)),
            'Profit':    profit,
            '% Profit':  pct,
            'Shares':    float(rng.integers(10, 100)),
            'Win':       profit > 0,
            '# bars':    float(rng.integers(2, 15)),
            'MAE':       float(rng.uniform(-2, 0)),
            'MFE':       float(rng.uniform(0, 3)),
            'Equity':    eq,
            'Cumulative_Profit': eq - 50_000,
            'RMultiple': float(rng.uniform(-2, 4)),
            'InitialRisk': 50.0,
            'Rolling_PF':    float(rng.uniform(0.5, 3.0)),
            'Rolling_Sharpe': float(rng.uniform(-1.5, 2.5)),
            'Entry YrMo': entry.strftime('%Y-%m'),
        })
    df = pd.DataFrame(rows)
    df['Date'] = pd.to_datetime(df['Date'])
    df['Ex. date'] = pd.to_datetime(df['Ex. date'])
    return df


def _make_report_data(trades_df: pd.DataFrame, out_dir: str) -> dict:
    """Build a minimal report_data dict for generate_tearsheet_pdf."""
    from trade_analyzer import calculations, data_handler
    from trade_analyzer import default_config as cfg

    initial_equity = 50_000.0
    daily_equity, daily_returns = data_handler.calculate_daily_returns(trades_df, initial_equity)
    core_raw = calculations.calculate_core_metrics(trades_df)
    dur_years = (
        (trades_df['Ex. date'].max() - trades_df['Date'].min()).days / 365.25
        if len(trades_df) > 1 else 1.0
    )
    _, _, _, max_dd = calculations.calculate_equity_drawdown(daily_equity if not daily_equity.empty else trades_df['Equity'])
    _, _, _, _, dd_periods_df = calculations.calculate_drawdown_details(
        trades_df['Cumulative_Profit'], trades_df['Ex. date']) if 'Cumulative_Profit' in trades_df.columns else (None, None, None, None, pd.DataFrame())
    equity_dd_series = pd.Series(dtype=float)
    if not daily_equity.empty:
        _, equity_dd_series, _, _ = calculations.calculate_equity_drawdown(daily_equity)

    # Monthly perf
    monthly_perf = (
        trades_df.groupby('Entry YrMo')['Profit']
        .sum().reset_index()
        .rename(columns={'Profit': 'Monthly_Profit'})
    ) if 'Entry YrMo' in trades_df else pd.DataFrame()

    # Symbol perf (minimal)
    symbol_perf = (
        trades_df.groupby('Symbol').agg(
            Total_Profit=('Profit', 'sum'),
            Win_Rate=('Win', 'mean'),
            Total_Trades=('Profit', 'size'),
            Profit_Factor=('Profit', lambda x: abs(x[x>0].sum()/x[x<=0].sum()) if x[x<=0].sum()!=0 else np.inf),
        )
    ) if 'Symbol' in trades_df else pd.DataFrame()
    symbol_perf['Win_Rate'] *= 100

    core = dict(core_raw)
    core['sharpe'] = calculations.calculate_sharpe_ratio(daily_returns, 0.0, 252)
    core['sortino'] = calculations.calculate_sortino_ratio(daily_returns, 0.0, 252)
    core['duration_years'] = dur_years

    return {
        'name':                 'Test Strategy',
        'run_date':             '2026-01-01',
        'trades_df':            trades_df,
        'initial_equity':       initial_equity,
        'daily_equity':         daily_equity,
        'daily_returns':        daily_returns,
        'benchmark_df':         None,
        'benchmark_returns':    pd.Series(dtype=float),
        'benchmark_ticker':     'SPY',
        'monthly_perf':         monthly_perf,
        'symbol_perf':          symbol_perf,
        'mc_results':           {},
        'mc_dd_neg':            True,
        'wfa_result':           {},
        'wfa_split_date':       None,
        'wfa_split_ratio':      None,
        'equity_dd_percent':    equity_dd_series,
        'dd_periods_df':        dd_periods_df if isinstance(dd_periods_df, pd.DataFrame) else pd.DataFrame(),
        'max_equity_dd_pct':    float(max_dd) if max_dd else 0.0,
        'core_metrics':         core,
        'risk_free_rate':       0.0,
        'rolling_window':       10,
        'cleaning_summary':     'No issues.',
        'overall_metrics_text': 'Total Trades: 30\nCAGR: 12.00%',
        'top_n_trades':         5,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestThemeApplication:
    def test_theme_rcparams_applied(self):
        """_apply_theme() updates font.family to the configured FONT_FAMILY."""
        from trade_analyzer.plotting import _apply_theme
        from trade_analyzer import default_config as cfg
        _apply_theme()
        import matplotlib.pyplot as plt
        assert plt.rcParams.get('font.family') == [cfg.FONT_FAMILY] or \
               plt.rcParams.get('font.family') == cfg.FONT_FAMILY

    def test_themed_context_restores_params(self):
        """themed() context manager restores rcParams after the block."""
        import matplotlib.pyplot as plt
        from trade_analyzer.plotting import themed
        original = plt.rcParams.get('font.size')
        with themed():
            pass
        assert plt.rcParams.get('font.size') == original


class TestKpiTile:
    def test_kpi_tile_renders_without_exception(self):
        """draw_kpi_tile() should not raise and should produce text in the axes."""
        from trade_analyzer._pdf_pages import draw_kpi_tile
        fig, ax = plt.subplots()
        ax.axis('off')
        draw_kpi_tile(ax, 'CAGR', '12.5%', subtitle='vs SPY +3%', positive=True)
        texts = ax.get_children()
        assert any(isinstance(t, matplotlib.text.Text) for t in texts)
        plt.close(fig)

    def test_kpi_tile_positive_false_does_not_raise(self):
        from trade_analyzer._pdf_pages import draw_kpi_tile
        fig, ax = plt.subplots()
        ax.axis('off')
        draw_kpi_tile(ax, 'Max DD', '−25.0%', positive=False)
        plt.close(fig)


class TestDataframeTable:
    def test_dataframe_table_renders_correct_size(self):
        """draw_dataframe_table() should add a Table to the axes."""
        from trade_analyzer._pdf_pages import draw_dataframe_table
        df = pd.DataFrame({
            'Symbol': ['AAPL', 'MSFT', 'GOOG'],
            'Profit': ['$1,000', '$500', '-$200'],
        })
        fig, ax = plt.subplots()
        draw_dataframe_table(ax, df, font_size=9)
        tables = [c for c in ax.get_children()
                  if isinstance(c, matplotlib.table.Table)]
        assert len(tables) == 1
        tbl = tables[0]
        # rows = nrows+1 (header), cols = ncols
        assert len(tbl.get_celld()) == (len(df) + 1) * len(df.columns)
        plt.close(fig)

    def test_empty_df_does_not_raise(self):
        from trade_analyzer._pdf_pages import draw_dataframe_table
        fig, ax = plt.subplots()
        draw_dataframe_table(ax, pd.DataFrame())
        plt.close(fig)


class TestMonthlyHeatmap:
    def test_heatmap_returns_figure(self):
        """plot_monthly_performance() with multi-year data returns a Figure."""
        from trade_analyzer.plotting import plot_monthly_performance
        monthly = pd.DataFrame({
            'Entry YrMo': ['2020-01', '2020-02', '2020-03',
                           '2021-01', '2021-06', '2021-12'],
            'Monthly_Profit': [1000, -500, 800, 1200, -300, 600],
            'Num_Trades': [5, 3, 4, 6, 2, 7],
        })
        fig = plot_monthly_performance(monthly)
        assert fig is not None
        assert isinstance(fig, plt.Figure)
        # Heatmap axes should have a title containing 'Heatmap' or similar
        titles = [ax.get_title() for ax in fig.get_axes()]
        assert any(t for t in titles)
        plt.close(fig)


class TestPdfGeneration:
    def test_report_runs_end_to_end(self, tmp_path):
        """generate_tearsheet_pdf() produces a PDF > 10 KB with a synthetic dataset."""
        from trade_analyzer._pdf_pages import generate_tearsheet_pdf

        trades_df = _make_trades(30)
        out_pdf = str(tmp_path / 'test_report.pdf')
        report_data = _make_report_data(trades_df, str(tmp_path))
        report_data['name'] = 'E2E Test Strategy'

        generate_tearsheet_pdf(report_data, out_pdf)

        assert os.path.exists(out_pdf), "PDF file was not created"
        size = os.path.getsize(out_pdf)
        assert size > 10_000, f"PDF is suspiciously small: {size} bytes"

    def test_pdf_page_count_within_target(self, tmp_path):
        """Tearsheet should have ≤ 14 pages."""
        from trade_analyzer._pdf_pages import generate_tearsheet_pdf
        try:
            import pypdf  # optional dep
            HAS_PYPDF = True
        except ImportError:
            try:
                import PyPDF2  # older name
                HAS_PYPDF = True
            except ImportError:
                HAS_PYPDF = False

        if not HAS_PYPDF:
            pytest.skip("pypdf not installed; skipping page-count check")

        trades_df = _make_trades(30)
        out_pdf = str(tmp_path / 'page_count_test.pdf')
        report_data = _make_report_data(trades_df, str(tmp_path))
        generate_tearsheet_pdf(report_data, out_pdf)

        try:
            import pypdf
            reader = pypdf.PdfReader(out_pdf)
            n_pages = len(reader.pages)
        except ImportError:
            import PyPDF2
            with open(out_pdf, 'rb') as f:
                reader = PyPDF2.PdfReader(f)
            n_pages = len(reader.pages)

        assert n_pages <= 14, f"PDF has {n_pages} pages (target ≤ 14)"

    def test_wfa_page_skipped_when_no_result(self, tmp_path):
        """build_wfa_page() returns None when wfa_result is empty."""
        from trade_analyzer._pdf_pages import build_wfa_page
        result = build_wfa_page({}, None, None, _make_trades(10), pd.Series(dtype=float))
        assert result is None

    def test_mc_page_skipped_when_no_data(self):
        """build_monte_carlo_page() returns None when mc_results is empty."""
        from trade_analyzer._pdf_pages import build_monte_carlo_page
        result = build_monte_carlo_page({}, 50_000, True)
        assert result is None

    def test_cover_page_contains_strategy_name(self):
        """Cover page should render strategy name in one of the text objects."""
        from trade_analyzer._pdf_pages import build_cover_page
        meta = {
            'name': 'My Fancy Strategy',
            'run_date': '2026-01-01',
            'start_date': '2020-01-01',
            'end_date': '2025-12-31',
            'total_return': 0.55,
            'cagr': 0.09,
            'max_dd': 0.22,
            'sharpe': 1.2,
            'profit_factor': 1.8,
            'total_trades': 250,
            'initial_equity': 50_000,
        }
        with plt.style.context('default'):
            fig = build_cover_page(meta)
        assert isinstance(fig, plt.Figure)
        all_texts = []
        for ax in fig.get_axes():
            all_texts.extend(t.get_text() for t in ax.get_children()
                             if isinstance(t, matplotlib.text.Text))
        # Title strip text lives on the banner_ax
        fig_texts = [t.get_text() for t in fig.texts]
        combined = all_texts + fig_texts
        assert any('My Fancy Strategy' in t for t in combined), \
            f"Strategy name not found in: {combined[:20]}"
        plt.close(fig)
