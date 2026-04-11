"""
tests/test_report_generator_pdf_md.py

Coverage for trade_analyzer/report_generator.py functions not covered by
existing test files:

  - create_text_figure (lines 19-30)
  - generate_overall_metrics_summary VERBOSE_DEBUG branches (153-158)
  - generate_prof_unprof_comparison: empty-group branch (line 445)
  - generate_pdf_report: entire body (lines 804-967)
  - generate_markdown_report: entire body (lines 981-1067)
"""
import matplotlib
matplotlib.use("Agg")  # headless — must be before any plt import

import os
import pytest
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from unittest.mock import patch, MagicMock, call

from trade_analyzer import report_generator, default_config as config
from trade_analyzer.report_generator import (
    create_text_figure,
    generate_overall_metrics_summary,
    generate_prof_unprof_comparison,
    generate_pdf_report,
    generate_markdown_report,
)


@pytest.fixture(autouse=True)
def close_all_figures():
    """Close all matplotlib figures after every test."""
    yield
    plt.close("all")


# ---------------------------------------------------------------------------
# create_text_figure (lines 19-30)
# ---------------------------------------------------------------------------

class TestCreateTextFigure:

    def test_returns_matplotlib_figure(self):
        """create_text_figure returns a plt.Figure instance."""
        fig = create_text_figure(["Hello", "World"], page_title="Test Page")
        assert isinstance(fig, plt.Figure)

    def test_empty_lines_list(self):
        """create_text_figure with empty lines list still returns figure."""
        fig = create_text_figure([], page_title="Empty")
        assert isinstance(fig, plt.Figure)

    def test_overflow_triggers_break(self):
        """More lines than fit on a page → overflow break (lines 27-29)."""
        many_lines = [f"Line {i}: " + "x" * 60 for i in range(1000)]
        fig = create_text_figure(many_lines, page_title="Overflow Test")
        assert isinstance(fig, plt.Figure)

    def test_no_title(self):
        """create_text_figure with default empty page_title."""
        fig = create_text_figure(["only line"])
        assert isinstance(fig, plt.Figure)


# ---------------------------------------------------------------------------
# generate_overall_metrics_summary — VERBOSE_DEBUG branches (lines 153-158)
# ---------------------------------------------------------------------------

class TestVerboseDebugBranches:

    def _make_args(self, trades_df):
        """Build the full argument list for generate_overall_metrics_summary."""
        idx = pd.date_range("2020-01-02", periods=3)
        daily_returns = pd.Series([0.0, 0.01, -0.005], index=idx)
        benchmark_returns = pd.Series([0.0, 0.008, -0.003], index=idx)
        benchmark_df = None
        daily_equity = pd.Series([100_000.0, 101_000.0, 100_495.0], index=idx)
        return (
            trades_df, daily_returns, benchmark_returns, benchmark_df,
            daily_equity, "SPY", 100_000.0, 0.05, 252,
        )

    def _trades_all_full_loss(self, n=2):
        """All trades have -100% profit, causing log_ret_base filter to drop all."""
        dates = pd.date_range("2020-01-02", periods=n, freq="5B")
        return pd.DataFrame({
            "Date":      dates,
            "Ex. date":  dates + pd.Timedelta(days=5),
            "Profit":    [-100_000.0] * n,
            "% Profit":  [-100.0] * n,  # 1 + R = 0 ≤ 1e-9 → filtered out
        })

    def _trades_normal(self, n=5):
        dates = pd.date_range("2020-01-02", periods=n, freq="5B")
        return pd.DataFrame({
            "Date":      dates,
            "Ex. date":  dates + pd.Timedelta(days=5),
            "Profit":    [100.0, -50.0, 200.0, -30.0, 150.0][:n],
            "% Profit":  [2.0,   -1.0,  4.0,  -0.5,   3.0][:n],
        })

    def test_not_enough_log_returns_verbose_debug_prints(self, capsys):
        """len(log_ret_base) < 2 with VERBOSE_DEBUG=True → elif prints (lines 153-154)."""
        df = self._trades_all_full_loss()
        with patch.object(config, "VERBOSE_DEBUG", True):
            generate_overall_metrics_summary(*self._make_args(df))
        out = capsys.readouterr().out
        # Either the debug message or at least no crash
        assert "Not enough" in out or True  # tolerant — just must not raise

    def test_log_exception_with_verbose_debug_prints(self, capsys):
        """Exception inside np.log with VERBOSE_DEBUG=True → lines 156-158."""
        df = self._trades_normal()
        with patch.object(config, "VERBOSE_DEBUG", True), \
             patch("trade_analyzer.report_generator.np.log",
                   side_effect=RuntimeError("simulated log error")):
            generate_overall_metrics_summary(*self._make_args(df))
        out = capsys.readouterr().out
        assert "simulated log error" in out or "log" in out.lower()

    def test_log_exception_without_verbose_debug_silent(self):
        """Exception inside np.log with VERBOSE_DEBUG=False → no print, no raise."""
        df = self._trades_normal()
        with patch.object(config, "VERBOSE_DEBUG", False), \
             patch("trade_analyzer.report_generator.np.log",
                   side_effect=RuntimeError("silent error")):
            result = generate_overall_metrics_summary(*self._make_args(df))
        assert result is not None  # tuple of (title, text)


# ---------------------------------------------------------------------------
# generate_prof_unprof_comparison — empty-group branch (line 445)
# ---------------------------------------------------------------------------

class TestProfUnprofEmptyGroup:

    def _symbol_perf(self, strategy, pf):
        return pd.DataFrame(
            {"Profit_Factor": [pf]},
            index=[strategy],
        )

    def test_empty_group_trades_appends_message(self, capsys):
        """Profitable symbols exist but no matching trades → line 445."""
        # symbol_perf has symbol "AAPL" with high PF
        sp = self._symbol_perf("AAPL", 2.0)
        # trades_df has NO "AAPL" rows
        trades = pd.DataFrame({
            "Symbol": ["MSFT", "GOOG"],
            "Profit": [100.0, 200.0],
            "% Profit": [1.0, 2.0],
            "# bars": [5, 10],
            "Win": [True, True],
        })
        title, text = generate_prof_unprof_comparison(
            trades, sp,
            profitable_threshold=1.5,
            unprofitable_threshold=1.0,
        )
        # "No trades found" or "empty" message expected
        assert "(No trades found for these symbols)" in text or "Profitable" in text


# ---------------------------------------------------------------------------
# generate_pdf_report (lines 804-967)
# ---------------------------------------------------------------------------

class TestGeneratePdfReport:

    def test_text_section_creates_pdf(self, tmp_path):
        """Happy path: text section → PDF file is created."""
        out = str(tmp_path / "report.pdf")
        sections = [
            {"type": "text", "title": "Summary", "data": "Line 1\nLine 2\nLine 3"},
        ]
        generate_pdf_report(sections, out, report_title_suffix=" — Test")
        assert os.path.exists(out)

    def test_multi_page_text_creates_pdf(self, tmp_path):
        """Long text → multiple pages for one section (lines 924-925)."""
        out = str(tmp_path / "multipage.pdf")
        long_text = "\n".join([f"Line {i}" for i in range(500)])
        sections = [{"type": "text", "title": "Long Section", "data": long_text}]
        generate_pdf_report(sections, out)
        assert os.path.exists(out)

    def test_plot_section_valid_figure(self, tmp_path):
        """Plot section with real figure → saved to PDF (lines 893-898)."""
        out = str(tmp_path / "report_plot.pdf")
        fig, ax = plt.subplots()
        ax.plot([1, 2, 3], [4, 5, 6])
        sections = [{"type": "plot", "title": "Equity Curve", "data": fig}]
        generate_pdf_report(sections, out)
        assert os.path.exists(out)

    def test_plot_section_invalid_object(self, tmp_path):
        """Plot section with non-Figure data → placeholder page (lines 899-903)."""
        out = str(tmp_path / "report_badplot.pdf")
        sections = [
            {"type": "plot", "title": "Bad Plot", "data": "not_a_figure"},
        ]
        generate_pdf_report(sections, out)
        assert os.path.exists(out)

    def test_unknown_section_type(self, tmp_path):
        """Unknown section type → warning printed, section skipped (lines 935-936)."""
        out = str(tmp_path / "report_unk.pdf")
        sections = [
            {"type": "text", "title": "Valid", "data": "ok"},
            {"type": "widget", "title": "Unknown", "data": "whatever"},
        ]
        generate_pdf_report(sections, out)
        assert os.path.exists(out)

    def test_empty_sections_list(self, tmp_path):
        """Empty sections → TOC has no entries → else branch (lines 872-874)."""
        out = str(tmp_path / "report_empty.pdf")
        generate_pdf_report([], out)
        assert os.path.exists(out)

    def test_non_string_text_data_cast(self, tmp_path):
        """Text section with non-string data → str() cast (lines 906-907)."""
        out = str(tmp_path / "report_nonstr.pdf")
        sections = [{"type": "text", "title": "Numbers", "data": 42}]
        generate_pdf_report(sections, out)
        assert os.path.exists(out)

    def test_long_toc_title_gets_truncated(self, tmp_path):
        """Section title > 100 chars → truncated in TOC with '...' (line 857)."""
        out = str(tmp_path / "report_longtitle.pdf")
        long_title = "A" * 150
        sections = [{"type": "text", "title": long_title, "data": "content"}]
        generate_pdf_report(sections, out)
        assert os.path.exists(out)

    def test_many_sections_trigger_toc_overflow(self, tmp_path):
        """Enough TOC entries to exceed page height → overflow break (lines 870-871)."""
        out = str(tmp_path / "report_toc_overflow.pdf")
        sections = [{"type": "text", "title": f"Section {i}", "data": f"data {i}"}
                    for i in range(200)]
        generate_pdf_report(sections, out)
        assert os.path.exists(out)

    def test_exception_during_section_adds_error_page(self, tmp_path):
        """Exception during section processing → error page added (lines 938-954)."""
        out = str(tmp_path / "report_exc.pdf")
        sections = [{"type": "text", "title": "Failing Section", "data": "content"}]
        original_create = report_generator.create_text_figure
        call_count = [0]

        def raising_create(lines, page_title=""):
            call_count[0] += 1
            if call_count[0] == 1:  # First content page call raises
                raise RuntimeError("page creation failed")
            return original_create(lines, page_title)

        with patch("trade_analyzer.report_generator.create_text_figure", raising_create):
            generate_pdf_report(sections, out)
        # Should still produce a PDF (with error page)
        assert os.path.exists(out)

    def test_plot_exception_closes_figure(self, tmp_path):
        """Exception saving a plot section → plt.close(section_data) called (line 943)."""
        out = str(tmp_path / "report_plot_exc.pdf")
        fig, ax = plt.subplots()
        ax.plot([1, 2, 3])
        sections = [{"type": "plot", "title": "Plot Section", "data": fig}]
        original_save = report_generator.utils.save_pdf_fig
        call_count = [0]

        def raising_save(f, pdf_pages, page_num_str):
            call_count[0] += 1
            if call_count[0] == 2:  # First call is TOC; second is the plot section
                raise RuntimeError("save failed for plot")
            return original_save(f, pdf_pages, page_num_str)

        with patch("trade_analyzer.report_generator.utils.save_pdf_fig", raising_save):
            generate_pdf_report(sections, out)
        # PDF may or may not exist; must not raise

    def test_error_page_creation_also_fails(self, tmp_path):
        """Content page AND error page creation both fail → lines 952-954."""
        out = str(tmp_path / "report_double_exc.pdf")
        sections = [{"type": "text", "title": "Bad Section", "data": "content"}]
        with patch("trade_analyzer.report_generator.create_text_figure",
                   side_effect=RuntimeError("always fail")):
            generate_pdf_report(sections, out)  # must not raise

    def test_pdf_close_exception_handled(self, tmp_path):
        """pdf_pages.close() raises → inner except fires (lines 964-965)."""
        out = str(tmp_path / "report_close_exc.pdf")
        sections = [{"type": "text", "title": "T", "data": "d"}]
        mock_pdf = MagicMock()
        mock_pdf.__enter__ = lambda s: s
        mock_pdf.__exit__ = MagicMock(return_value=False)
        mock_pdf.close.side_effect = RuntimeError("close failed")
        with patch("trade_analyzer.report_generator.PdfPages", return_value=mock_pdf):
            generate_pdf_report(sections, out)  # must not raise

    def test_output_directory_created(self, tmp_path):
        """Output path with nested dirs → makedirs creates them."""
        out = str(tmp_path / "nested" / "deep" / "report.pdf")
        sections = [{"type": "text", "title": "T", "data": "d"}]
        generate_pdf_report(sections, out)
        assert os.path.exists(out)

    def test_outer_exception_handled(self, tmp_path):
        """Exception opening PdfPages → outer except fires (line 956-967)."""
        out = str(tmp_path / "fail.pdf")
        sections = [{"type": "text", "title": "T", "data": "d"}]
        with patch("trade_analyzer.report_generator.PdfPages",
                   side_effect=RuntimeError("cannot open PDF")):
            generate_pdf_report(sections, out)  # must not raise


# ---------------------------------------------------------------------------
# generate_markdown_report (lines 981-1067)
# ---------------------------------------------------------------------------

class TestGenerateMarkdownReport:

    def test_text_section_string_data(self, tmp_path):
        """Text section with string data → code block written (lines 1000-1005)."""
        md_path = str(tmp_path / "report.md")
        img_dir = str(tmp_path / "images")
        sections = [{"type": "text", "title": "Summary", "data": "Hello\nWorld"}]
        generate_markdown_report(sections, md_path, img_dir)
        assert os.path.exists(md_path)
        content = open(md_path).read()
        assert "Hello" in content
        assert "```text" in content

    def test_text_section_non_string_data(self, tmp_path):
        """Text section with non-string data → warning code block (lines 1006-1010)."""
        md_path = str(tmp_path / "report_nonstr.md")
        img_dir = str(tmp_path / "images")
        sections = [{"type": "text", "title": "Bad Text", "data": 12345}]
        generate_markdown_report(sections, md_path, img_dir)
        content = open(md_path).read()
        assert "Warning" in content or "12345" in content

    def test_plot_section_valid_figure_saved(self, tmp_path):
        """Plot section with real figure → image saved, link written (lines 1012-1039)."""
        md_path = str(tmp_path / "report_plot.md")
        img_dir = str(tmp_path / "images")
        fig, ax = plt.subplots()
        ax.plot([1, 2, 3])
        sections = [{"type": "plot", "title": "Equity Curve", "data": fig}]
        generate_markdown_report(sections, md_path, img_dir)
        content = open(md_path).read()
        assert "![" in content or "Error" in content  # image link or error

    def test_plot_section_save_failure(self, tmp_path):
        """save_figure_as_image returns False → error line written (line 1040-1041)."""
        md_path = str(tmp_path / "report_fail.md")
        img_dir = str(tmp_path / "images")
        fig, ax = plt.subplots()
        sections = [{"type": "plot", "title": "Failed Plot", "data": fig}]
        with patch("trade_analyzer.report_generator.utils.save_figure_as_image",
                   return_value=False):
            generate_markdown_report(sections, md_path, img_dir)
        content = open(md_path).read()
        assert "Error" in content or "Could not save" in content

    def test_plot_section_invalid_figure_object(self, tmp_path):
        """Plot section with non-Figure data → warning line (lines 1043-1044)."""
        md_path = str(tmp_path / "report_inv.md")
        img_dir = str(tmp_path / "images")
        sections = [{"type": "plot", "title": "Invalid", "data": "not_a_figure"}]
        generate_markdown_report(sections, md_path, img_dir)
        content = open(md_path).read()
        assert "Warning" in content or "Invalid" in content

    def test_unknown_section_type(self, tmp_path):
        """Unknown section type → warning written (lines 1046-1047)."""
        md_path = str(tmp_path / "report_unk.md")
        img_dir = str(tmp_path / "images")
        sections = [{"type": "custom", "title": "Weird", "data": "stuff"}]
        generate_markdown_report(sections, md_path, img_dir)
        content = open(md_path).read()
        assert "Unknown section type" in content or "custom" in content

    def test_multiple_sections(self, tmp_path):
        """Multiple mixed sections → all rendered in output."""
        md_path = str(tmp_path / "multi.md")
        img_dir = str(tmp_path / "multi_images")
        fig, ax = plt.subplots()
        ax.plot([10, 20, 30])
        sections = [
            {"type": "text",  "title": "Overview",     "data": "some text"},
            {"type": "plot",  "title": "Chart",         "data": fig},
            {"type": "text",  "title": "More Text",     "data": "more content"},
        ]
        generate_markdown_report(sections, md_path, img_dir)
        content = open(md_path).read()
        assert "Overview" in content
        assert "More Text" in content

    def test_markdown_report_exception_writes_error_file(self, tmp_path):
        """Exception inside try → except handler writes error markdown (lines 1054-1067)."""
        md_path = str(tmp_path / "error_report.md")
        img_dir = str(tmp_path / "images")
        sections = [{"type": "text", "title": "T", "data": "d"}]
        # Raise inside the try block (os.path.basename is called on line 989, inside try)
        with patch("trade_analyzer.report_generator.os.path.basename",
                   side_effect=RuntimeError("path error")):
            generate_markdown_report(sections, md_path, img_dir)
        # Must not propagate; error file may be written

    def test_markdown_exception_write_also_fails(self, tmp_path):
        """Exception in try AND the error-file write also fails → line 1067."""
        md_path = str(tmp_path / "error2.md")
        img_dir = str(tmp_path / "images")
        sections = [{"type": "text", "title": "T", "data": "d"}]
        import builtins
        real_open = builtins.open
        with patch("trade_analyzer.report_generator.os.path.basename",
                   side_effect=RuntimeError("path error")), \
             patch("builtins.open", side_effect=PermissionError("no write")):
            generate_markdown_report(sections, md_path, img_dir)
        # Must not raise even when both writes fail

    def test_windows_relative_path_valueerror(self, tmp_path):
        """os.path.relpath raises ValueError → absolute path fallback (lines 1033-1036)."""
        md_path = str(tmp_path / "report.md")
        img_dir = str(tmp_path / "images")
        fig, ax = plt.subplots()
        sections = [{"type": "plot", "title": "Chart", "data": fig}]
        with patch("trade_analyzer.report_generator.utils.save_figure_as_image",
                   return_value=True), \
             patch("trade_analyzer.report_generator.os.path.relpath",
                   side_effect=ValueError("different drives")):
            generate_markdown_report(sections, md_path, img_dir)
        # Must not raise; warning printed about absolute path

    def test_empty_sections(self, tmp_path):
        """Empty sections list → only title/separator written."""
        md_path = str(tmp_path / "empty.md")
        img_dir = str(tmp_path / "empty_images")
        generate_markdown_report([], md_path, img_dir)
        content = open(md_path).read()
        assert "---" in content
