"""
Tests for trade_analyzer/utils.py.

Covers save_pdf_fig and save_figure_as_image guard clauses and success paths.
Real matplotlib figures used for save paths; PdfPages is mocked.
"""
import os
import pytest
import matplotlib
matplotlib.use("Agg")  # non-interactive backend — no display required
import matplotlib.pyplot as plt
from unittest.mock import MagicMock, patch

from trade_analyzer.utils import save_pdf_fig, save_figure_as_image


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fig():
    """Create a minimal matplotlib figure."""
    fig, ax = plt.subplots()
    ax.plot([1, 2, 3], [1, 4, 9])
    return fig


def _make_pdf_pages():
    """Return a MagicMock that satisfies the PdfPages interface."""
    return MagicMock()


# ---------------------------------------------------------------------------
# save_pdf_fig — guard clauses
# ---------------------------------------------------------------------------

class TestSavePdfFigGuards:

    def test_none_figure_skips_save(self):
        """None figure → prints warning, returns without saving."""
        pdf = _make_pdf_pages()
        save_pdf_fig(None, pdf, "1")
        pdf.savefig.assert_not_called()

    def test_non_figure_object_skips_save(self):
        """Passing a plain string instead of a Figure → prints warning, skips."""
        pdf = _make_pdf_pages()
        save_pdf_fig("not a figure", pdf, "1")
        pdf.savefig.assert_not_called()

    def test_integer_instead_of_figure_skips_save(self):
        pdf = _make_pdf_pages()
        save_pdf_fig(42, pdf, "2")
        pdf.savefig.assert_not_called()


# ---------------------------------------------------------------------------
# save_pdf_fig — success path
# ---------------------------------------------------------------------------

class TestSavePdfFigSuccess:

    def test_valid_figure_calls_savefig(self):
        """A live figure is saved to the pdf_pages object."""
        fig = _make_fig()
        pdf = _make_pdf_pages()
        save_pdf_fig(fig, pdf, "Page 1")
        pdf.savefig.assert_called_once()

    def test_valid_figure_is_closed_after_save(self):
        """Figure must be closed after saving to free memory."""
        fig = _make_fig()
        fig_num = fig.number
        pdf = _make_pdf_pages()
        save_pdf_fig(fig, pdf, "1")
        assert not plt.fignum_exists(fig_num)

    def test_savefig_exception_still_closes_figure(self):
        """Even if pdf.savefig raises, the figure should be closed."""
        fig = _make_fig()
        fig_num = fig.number
        pdf = _make_pdf_pages()
        pdf.savefig.side_effect = Exception("disk full")
        save_pdf_fig(fig, pdf, "1")
        assert not plt.fignum_exists(fig_num)


# ---------------------------------------------------------------------------
# save_figure_as_image — guard clauses
# ---------------------------------------------------------------------------

class TestSaveFigureAsImageGuards:

    def test_none_figure_returns_false(self):
        result = save_figure_as_image(None, "/tmp/out.png")
        assert result is False

    def test_non_figure_object_returns_false(self):
        result = save_figure_as_image("not a figure", "/tmp/out.png")
        assert result is False

    def test_dict_instead_of_figure_returns_false(self):
        result = save_figure_as_image({}, "/tmp/out.png")
        assert result is False


# ---------------------------------------------------------------------------
# save_figure_as_image — success path
# ---------------------------------------------------------------------------

class TestSaveFigureAsImageSuccess:

    def test_valid_figure_saves_file(self, tmp_path):
        """A live figure is saved to disk and True is returned."""
        fig = _make_fig()
        out = str(tmp_path / "chart.png")
        result = save_figure_as_image(fig, out)
        assert result is True
        assert os.path.isfile(out)
        plt.close(fig)

    def test_creates_output_directory_if_missing(self, tmp_path):
        """Output directory is created automatically."""
        fig = _make_fig()
        out = str(tmp_path / "subdir" / "deep" / "chart.png")
        result = save_figure_as_image(fig, out)
        assert result is True
        assert os.path.isfile(out)
        plt.close(fig)

    def test_figure_not_closed_after_image_save(self, tmp_path):
        """save_figure_as_image does NOT close the figure (unlike save_pdf_fig)."""
        fig = _make_fig()
        fig_num = fig.number
        out = str(tmp_path / "chart.png")
        save_figure_as_image(fig, out)
        assert plt.fignum_exists(fig_num)
        plt.close(fig)

    def test_closed_figure_returns_false(self):
        """If the figure is closed before saving, returns False."""
        fig = _make_fig()
        fig_num = fig.number
        plt.close(fig)
        result = save_figure_as_image(fig, "/tmp/shouldnotexist.png")
        assert result is False

    def test_exception_during_save_returns_false(self, tmp_path):
        """OS error during savefig returns False without raising."""
        fig = _make_fig()
        out = str(tmp_path / "chart.png")
        with patch.object(fig, "savefig", side_effect=OSError("no space")):
            result = save_figure_as_image(fig, out)
        assert result is False
        plt.close(fig)
