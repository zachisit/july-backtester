"""Tests for helpers.verdict_format — strategy-verdict block formatter."""

import io

import pytest

from helpers import verdict_format


def _result(**overrides):
    base = {
        "Strategy": "EC-VIX-27",
        "Portfolio": "NDX+Energy+Defense",
        "Trades": 100,
        "pnl_percent": 32.5,
        "vs_spy_benchmark": 25.2,
        "mc_verdict": "DD Understated, High Tail Risk",
        "mc_score": -1,
        "wfa_verdict": "Pass",
        "wfa_rolling_verdict": "Pass (5/5)",
        "smooth_verdict": "ACCEPTABLE",
        "smooth_notes": ["plateau: 21 consecutive months without new high"],
    }
    base.update(overrides)
    return base


_BENCH = {"SPY": 7.3}  # 730% fractional


class TestFormatStrategyVerdictLines:
    def test_returns_list_of_strings(self):
        lines = verdict_format.format_strategy_verdict_lines(_result(), _BENCH)
        assert isinstance(lines, list)
        assert all(isinstance(l, str) for l in lines)

    def test_header_contains_strategy_and_portfolio(self):
        lines = verdict_format.format_strategy_verdict_lines(_result(), _BENCH)
        assert "EC-VIX-27" in lines[0]
        assert "NDX+Energy+Defense" in lines[0]

    def test_header_without_portfolio_omits_parens(self):
        lines = verdict_format.format_strategy_verdict_lines(_result(Portfolio=""), _BENCH)
        assert lines[0].strip() == "EC-VIX-27"

    def test_beats_verdict_format(self):
        # pnl_percent=32.5 (3250%) vs SPY 7.3 (730%) -> +2520pp -> verdict positive
        # vs_spy_benchmark is set to 25.2 directly -> +2520pp
        lines = verdict_format.format_strategy_verdict_lines(_result(), _BENCH)
        verdict_line = next(l for l in lines if "Verdict:" in l)
        assert "BEATS SPY" in verdict_line
        assert "+2520.00pp" in verdict_line

    def test_lags_verdict_format(self):
        lines = verdict_format.format_strategy_verdict_lines(
            _result(vs_spy_benchmark=-0.50), _BENCH,
        )
        verdict_line = next(l for l in lines if "Verdict:" in l)
        assert "LAGS SPY" in verdict_line
        assert "-50.00pp" in verdict_line

    def test_mc_verdict_with_score(self):
        lines = verdict_format.format_strategy_verdict_lines(_result(), _BENCH)
        mc_line = next(l for l in lines if "MC:" in l)
        assert "DD Understated, High Tail Risk" in mc_line
        assert "score: -1" in mc_line

    def test_mc_verdict_without_score(self):
        lines = verdict_format.format_strategy_verdict_lines(
            _result(mc_score=None), _BENCH,
        )
        mc_line = next(l for l in lines if "MC:" in l)
        assert "score:" not in mc_line

    def test_wfa_combined_line(self):
        lines = verdict_format.format_strategy_verdict_lines(_result(), _BENCH)
        wfa_line = next(l for l in lines if "WFA:" in l)
        assert "Pass" in wfa_line
        assert "Rolling:" in wfa_line
        assert "Pass (5/5)" in wfa_line

    def test_smoothness_line_with_notes(self):
        lines = verdict_format.format_strategy_verdict_lines(_result(), _BENCH)
        smooth_line = next(l for l in lines if "Smoothness:" in l)
        assert "ACCEPTABLE" in smooth_line
        note_line = next(l for l in lines if "plateau:" in l)
        assert note_line.lstrip().startswith("- plateau:")

    def test_smoothness_no_notes_omits_bullets(self):
        lines = verdict_format.format_strategy_verdict_lines(
            _result(smooth_notes=[]), _BENCH,
        )
        assert not any("- " in l and l.lstrip().startswith("- ") for l in lines)

    def test_missing_benchmark_no_verdict_line_value(self):
        lines = verdict_format.format_strategy_verdict_lines(_result(), None)
        verdict_line = next(l for l in lines if "Verdict:" in l)
        assert "no benchmark configured" in verdict_line

    def test_uses_pnl_margin_fallback_when_no_precomputed_key(self):
        r = _result()
        r.pop("vs_spy_benchmark")
        # pnl_percent 32.5, bench 7.3 -> margin 25.2 -> +2520pp
        lines = verdict_format.format_strategy_verdict_lines(r, _BENCH)
        verdict_line = next(l for l in lines if "Verdict:" in l)
        assert "+2520.00pp" in verdict_line


class TestFormatBlock:
    def test_block_contains_header(self):
        text = verdict_format.format_strategy_verdicts_block([_result()], _BENCH)
        assert "STRATEGY VERDICTS" in text

    def test_block_contains_each_strategy(self):
        rs = [_result(Strategy="A"), _result(Strategy="B")]
        text = verdict_format.format_strategy_verdicts_block(rs, _BENCH)
        assert "A " in text or "A\n" in text
        assert "B " in text or "B\n" in text

    def test_block_skips_zero_trades(self):
        rs = [_result(Strategy="HasTrades", Trades=10),
              _result(Strategy="NoTrades", Trades=0)]
        text = verdict_format.format_strategy_verdicts_block(rs, _BENCH)
        assert "HasTrades" in text
        assert "NoTrades" not in text


class TestPrintFunction:
    def test_prints_to_stdout(self, capsys):
        verdict_format.print_strategy_verdicts([_result()], _BENCH)
        out = capsys.readouterr().out
        assert "STRATEGY VERDICTS" in out
        assert "EC-VIX-27" in out

    def test_empty_results_noop(self, capsys):
        verdict_format.print_strategy_verdicts([], _BENCH)
        out = capsys.readouterr().out
        assert out == ""

    def test_zero_trades_only_noop(self, capsys):
        verdict_format.print_strategy_verdicts([_result(Trades=0)], _BENCH)
        out = capsys.readouterr().out
        assert out == ""

    def test_prints_to_custom_file(self):
        buf = io.StringIO()
        verdict_format.print_strategy_verdicts([_result()], _BENCH, file=buf)
        assert "STRATEGY VERDICTS" in buf.getvalue()
