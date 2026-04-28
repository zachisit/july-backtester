"""tests/test_cli_config.py — unit tests for helpers/cli_config.py

No subprocess, no file I/O, no network. All tests operate on the module
functions directly so they run fast and deterministically.
"""
from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout

import pytest

from helpers.cli_config import (
    VALID_CATEGORIES,
    apply_overrides,
    build_parser,
    cast_value,
    parse_stop_token,
    print_help_config,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse(argv: list[str]):
    """Parse a list of CLI tokens using build_parser()."""
    return build_parser().parse_args(argv)


def _cfg(**overrides) -> dict:
    """Minimal config dict for apply_overrides tests."""
    base = {
        "data_provider": "norgate",
        "csv_data_dir": "csv_data",
        "parquet_data_dir": "parquet_data",
        "start_date": "2004-01-01",
        "end_date": "2026-01-01",
        "initial_capital": 100_000.0,
        "portfolios": {"Default": ["AAPL"]},
        "strategies": "all",
        "allocation_per_trade": 0.10,
        "execution_time": "open",
        "slippage_pct": 0.0005,
        "commission_per_share": 0.002,
        "risk_free_rate": 0.05,
        "htb_rate_annual": 0.02,
        "max_pct_adv": 0.05,
        "volume_impact_coeff": 0.0,
        "stop_loss_configs": [{"type": "none"}],
        "min_pandl_to_show_in_summary": -9999,
        "max_acceptable_drawdown": 1.0,
        "mc_score_min_to_show_in_summary": -9999,
        "min_performance_vs_spy": -9999,
        "num_mc_simulations": 1000,
        "min_trades_for_mc": 50,
        "mc_sampling": "iid",
        "wfa_split_ratio": 0.80,
        "wfa_folds": None,
        "save_individual_trades": True,
        "save_only_filtered_trades": False,
        "noise_injection_pct": 0.0,
        "rolling_sharpe_window": 126,
        "export_ml_features": False,
        "upload_to_s3": False,
        "min_bars_required": 250,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# TestParseStopToken
# ---------------------------------------------------------------------------

class TestParseStopToken:
    def test_none(self):
        assert parse_stop_token("none") == {"type": "none"}

    def test_pct(self):
        assert parse_stop_token("pct:0.05") == {"type": "percentage", "value": 0.05}

    def test_atr(self):
        result = parse_stop_token("atr:14:3.0")
        assert result == {"type": "atr", "period": 14, "multiplier": 3.0}

    def test_invalid_token_raises(self):
        with pytest.raises(ValueError, match="Unknown stop token"):
            parse_stop_token("fixed:100")

    def test_case_insensitive(self):
        assert parse_stop_token("NONE") == {"type": "none"}
        assert parse_stop_token("PCT:0.10") == {"type": "percentage", "value": 0.10}
        assert parse_stop_token("ATR:20:2.5") == {"type": "atr", "period": 20, "multiplier": 2.5}

    def test_pct_missing_value_raises(self):
        with pytest.raises(ValueError):
            parse_stop_token("pct:")

    def test_atr_missing_parts_raises(self):
        with pytest.raises(ValueError):
            parse_stop_token("atr:14")


# ---------------------------------------------------------------------------
# TestCastValue
# ---------------------------------------------------------------------------

class TestCastValue:
    def test_int(self):
        assert cast_value("42") == 42
        assert isinstance(cast_value("42"), int)

    def test_float(self):
        result = cast_value("3.14")
        assert abs(result - 3.14) < 1e-9
        assert isinstance(result, float)

    def test_true(self):
        assert cast_value("true") is True
        assert cast_value("True") is True
        assert cast_value("TRUE") is True

    def test_false(self):
        assert cast_value("false") is False
        assert cast_value("False") is False

    def test_string_passthrough(self):
        assert cast_value("norgate") == "norgate"
        assert cast_value("block") == "block"


# ---------------------------------------------------------------------------
# TestApplyOverrides
# ---------------------------------------------------------------------------

class TestApplyOverrides:
    def test_provider(self):
        cfg = _cfg()
        apply_overrides(cfg, _parse(["--provider", "yahoo"]))
        assert cfg["data_provider"] == "yahoo"

    def test_start_date(self):
        cfg = _cfg()
        apply_overrides(cfg, _parse(["--start", "2018-01-01"]))
        assert cfg["start_date"] == "2018-01-01"

    def test_capital(self):
        cfg = _cfg()
        apply_overrides(cfg, _parse(["--capital", "75000"]))
        assert cfg["initial_capital"] == 75_000.0

    def test_symbols_builds_cli_portfolio(self):
        cfg = _cfg()
        apply_overrides(cfg, _parse(["--symbols", "AAPL", "MSFT"]))
        assert cfg["portfolios"] == {"CLI": ["AAPL", "MSFT"]}

    def test_portfolio_file_builds_cli_portfolio(self):
        cfg = _cfg()
        apply_overrides(cfg, _parse(["--portfolio", "nasdaq_100.json"]))
        assert cfg["portfolios"] == {"CLI": "nasdaq_100.json"}

    def test_symbols_and_portfolio_are_mutually_exclusive(self):
        with pytest.raises(SystemExit):
            _parse(["--symbols", "AAPL", "--portfolio", "nasdaq_100.json"])

    def test_strategies_list(self):
        cfg = _cfg()
        apply_overrides(cfg, _parse(["--strategies", "SMA Crossover (20d/50d)"]))
        assert cfg["strategies"] == ["SMA Crossover (20d/50d)"]

    def test_strategies_all(self):
        cfg = _cfg(strategies=["SMA Crossover (20d/50d)"])
        apply_overrides(cfg, _parse(["--strategies", "all"]))
        assert cfg["strategies"] == "all"

    def test_allocation(self):
        cfg = _cfg()
        apply_overrides(cfg, _parse(["--allocation", "0.05"]))
        assert cfg["allocation_per_trade"] == pytest.approx(0.05)

    def test_stop_single(self):
        cfg = _cfg()
        apply_overrides(cfg, _parse(["--stop", "none"]))
        assert cfg["stop_loss_configs"] == [{"type": "none"}]

    def test_stop_multiple(self):
        cfg = _cfg()
        apply_overrides(cfg, _parse(["--stop", "none", "pct:0.05"]))
        assert cfg["stop_loss_configs"] == [
            {"type": "none"},
            {"type": "percentage", "value": 0.05},
        ]

    def test_stop_atr(self):
        cfg = _cfg()
        apply_overrides(cfg, _parse(["--stop", "atr:14:3.0"]))
        assert cfg["stop_loss_configs"] == [{"type": "atr", "period": 14, "multiplier": 3.0}]

    def test_min_pandl(self):
        cfg = _cfg()
        apply_overrides(cfg, _parse(["--min-pandl", "10.0"]))
        assert cfg["min_pandl_to_show_in_summary"] == pytest.approx(10.0)

    def test_max_dd(self):
        cfg = _cfg()
        apply_overrides(cfg, _parse(["--max-dd", "0.30"]))
        assert cfg["max_acceptable_drawdown"] == pytest.approx(0.30)

    def test_mc_sims(self):
        cfg = _cfg()
        apply_overrides(cfg, _parse(["--mc-sims", "500"]))
        assert cfg["num_mc_simulations"] == 500

    def test_wfa_split(self):
        cfg = _cfg()
        apply_overrides(cfg, _parse(["--wfa-split", "0.70"]))
        assert cfg["wfa_split_ratio"] == pytest.approx(0.70)

    def test_wfa_split_zero_disables_wfa(self):
        cfg = _cfg()
        apply_overrides(cfg, _parse(["--wfa-split", "0"]))
        assert cfg["wfa_split_ratio"] is None

    def test_wfa_folds_zero_disables_rolling(self):
        cfg = _cfg(wfa_folds=5)
        apply_overrides(cfg, _parse(["--wfa-folds", "0"]))
        assert cfg["wfa_folds"] is None

    def test_no_save_trades(self):
        cfg = _cfg()
        apply_overrides(cfg, _parse(["--no-save-trades"]))
        assert cfg["save_individual_trades"] is False

    def test_save_trades_on(self):
        cfg = _cfg(save_individual_trades=False)
        apply_overrides(cfg, _parse(["--save-trades"]))
        assert cfg["save_individual_trades"] is True

    def test_export_ml(self):
        cfg = _cfg()
        apply_overrides(cfg, _parse(["--export-ml"]))
        assert cfg["export_ml_features"] is True

    def test_set_escape_hatch_float(self):
        cfg = _cfg()
        apply_overrides(cfg, _parse(["--set", "noise_injection_pct=0.01"]))
        assert cfg["noise_injection_pct"] == pytest.approx(0.01)

    def test_set_escape_hatch_int(self):
        cfg = _cfg()
        apply_overrides(cfg, _parse(["--set", "wfa_folds=5"]))
        assert cfg["wfa_folds"] == 5

    def test_set_escape_hatch_bool(self):
        cfg = _cfg()
        apply_overrides(cfg, _parse(["--set", "export_ml_features=true"]))
        assert cfg["export_ml_features"] is True

    def test_set_escape_hatch_string(self):
        cfg = _cfg()
        apply_overrides(cfg, _parse(["--set", "mc_sampling=block"]))
        assert cfg["mc_sampling"] == "block"

    def test_set_escape_hatch_repeatable(self):
        cfg = _cfg()
        apply_overrides(cfg, _parse(["--set", "mc_sampling=block", "--set", "min_trades_for_mc=30"]))
        assert cfg["mc_sampling"] == "block"
        assert cfg["min_trades_for_mc"] == 30

    def test_no_override_when_flag_not_given(self):
        """Flags not passed must not overwrite existing config values."""
        cfg = _cfg(start_date="2010-01-01")
        apply_overrides(cfg, _parse(["--capital", "50000"]))
        assert cfg["start_date"] == "2010-01-01"  # unchanged

    def test_slippage(self):
        cfg = _cfg()
        apply_overrides(cfg, _parse(["--slippage", "0.001"]))
        assert cfg["slippage_pct"] == pytest.approx(0.001)

    def test_mc_sampling(self):
        cfg = _cfg()
        apply_overrides(cfg, _parse(["--mc-sampling", "block"]))
        assert cfg["mc_sampling"] == "block"

    def test_risk_free_rate(self):
        cfg = _cfg()
        apply_overrides(cfg, _parse(["--risk-free-rate", "0.04"]))
        assert cfg["risk_free_rate"] == pytest.approx(0.04)

    def test_min_bars(self):
        cfg = _cfg()
        apply_overrides(cfg, _parse(["--min-bars", "500"]))
        assert cfg["min_bars_required"] == 500

    def test_noise(self):
        cfg = _cfg()
        apply_overrides(cfg, _parse(["--noise", "0.01"]))
        assert cfg["noise_injection_pct"] == pytest.approx(0.01)

    def test_rolling_sharpe(self):
        cfg = _cfg()
        apply_overrides(cfg, _parse(["--rolling-sharpe", "63"]))
        assert cfg["rolling_sharpe_window"] == 63

    def test_upload_s3(self):
        cfg = _cfg()
        apply_overrides(cfg, _parse(["--upload-s3"]))
        assert cfg["upload_to_s3"] is True

    def test_commission(self):
        cfg = _cfg()
        apply_overrides(cfg, _parse(["--commission", "0.005"]))
        assert cfg["commission_per_share"] == pytest.approx(0.005)

    def test_htb_rate(self):
        cfg = _cfg()
        apply_overrides(cfg, _parse(["--htb-rate", "0.10"]))
        assert cfg["htb_rate_annual"] == pytest.approx(0.10)

    def test_volume_impact(self):
        cfg = _cfg()
        apply_overrides(cfg, _parse(["--volume-impact", "0.1"]))
        assert cfg["volume_impact_coeff"] == pytest.approx(0.1)

    def test_min_mc_score(self):
        cfg = _cfg()
        apply_overrides(cfg, _parse(["--min-mc-score", "50"]))
        assert cfg["mc_score_min_to_show_in_summary"] == pytest.approx(50.0)

    def test_min_vs_spy(self):
        cfg = _cfg()
        apply_overrides(cfg, _parse(["--min-vs-spy", "0.0"]))
        assert cfg["min_performance_vs_spy"] == pytest.approx(0.0)

    def test_execution_time(self):
        cfg = _cfg()
        apply_overrides(cfg, _parse(["--execution", "close"]))
        assert cfg["execution_time"] == "close"

    def test_provider_parquet_and_dir(self):
        cfg = _cfg()
        apply_overrides(cfg, _parse(["--provider", "parquet", "--parquet-dir", "./my_data"]))
        assert cfg["data_provider"] == "parquet"
        assert cfg["parquet_data_dir"] == "./my_data"

    def test_wfa_folds_set(self):
        cfg = _cfg()
        apply_overrides(cfg, _parse(["--wfa-folds", "5"]))
        assert cfg["wfa_folds"] == 5

    def test_save_filtered_only(self):
        cfg = _cfg()
        apply_overrides(cfg, _parse(["--save-filtered-only"]))
        assert cfg["save_only_filtered_trades"] is True

    def test_min_trades_mc(self):
        cfg = _cfg()
        apply_overrides(cfg, _parse(["--min-trades-mc", "30"]))
        assert cfg["min_trades_for_mc"] == 30


# ---------------------------------------------------------------------------
# TestBuildParser
# ---------------------------------------------------------------------------

class TestBuildParser:
    def test_returns_argument_parser(self):
        import argparse
        parser = build_parser()
        assert isinstance(parser, argparse.ArgumentParser)

    def test_help_config_flag_exists(self):
        parser = build_parser()
        # --help-config should be parseable with and without a value
        args = parser.parse_args(["--help-config"])
        assert args.help_config == "all"
        args2 = parser.parse_args(["--help-config", "mc"])
        assert args2.help_config == "mc"

    def test_existing_flags_still_work(self):
        args = _parse(["--name", "myrun", "--dry-run", "--verbose"])
        assert args.name == "myrun"
        assert args.dry_run is True
        assert args.verbose is True

    def test_all_expected_dests_present(self):
        args = _parse([])
        expected_dests = [
            "data_provider", "csv_data_dir", "parquet_data_dir",
            "start_date", "end_date", "initial_capital",
            "symbols", "portfolio", "min_bars_required",
            "strategies", "allocation_per_trade", "execution_time",
            "slippage_pct", "commission_per_share", "risk_free_rate",
            "htb_rate_annual", "max_pct_adv", "volume_impact_coeff",
            "stop_tokens",
            "min_pandl_to_show_in_summary", "max_acceptable_drawdown",
            "mc_score_min_to_show_in_summary", "min_performance_vs_spy",
            "num_mc_simulations", "min_trades_for_mc", "mc_sampling",
            "wfa_split_ratio", "wfa_folds",
            "save_individual_trades", "save_only_filtered_trades",
            "noise_injection_pct", "rolling_sharpe_window",
            "export_ml_features", "upload_to_s3",
            "overrides",
        ]
        for dest in expected_dests:
            assert hasattr(args, dest), f"Expected dest '{dest}' missing from parser"

    def test_no_args_leaves_all_none(self):
        args = _parse([])
        assert args.data_provider is None
        assert args.start_date is None
        assert args.initial_capital is None
        assert args.symbols is None
        assert args.overrides is None


# ---------------------------------------------------------------------------
# TestPrintHelpConfig
# ---------------------------------------------------------------------------

class TestPrintHelpConfig:
    def _capture(self, cfg, category=None) -> str:
        buf = io.StringIO()
        with redirect_stdout(buf):
            print_help_config(cfg, category)
        return buf.getvalue()

    def test_full_print_contains_all_section_titles(self):
        out = self._capture(_cfg())
        assert "DATA" in out
        assert "PERIOD" in out
        assert "MONTE CARLO" in out
        assert "WALK-FORWARD" in out
        assert "STOP LOSS" in out

    def test_full_print_shows_current_value(self):
        cfg = _cfg(start_date="2015-01-01")
        out = self._capture(cfg)
        assert "2015-01-01" in out

    def test_category_data_excludes_mc(self):
        out = self._capture(_cfg(), category="data")
        assert "--provider" in out
        assert "MONTE CARLO" not in out

    def test_category_mc_contains_mc_section(self):
        out = self._capture(_cfg(), category="mc")
        assert "--mc-sims" in out
        assert "--mc-sampling" in out

    def test_category_wfa_contains_wfa_section(self):
        out = self._capture(_cfg(), category="wfa")
        assert "--wfa-split" in out
        assert "--wfa-folds" in out

    def test_unknown_category_shows_error_and_valid_list(self):
        out = self._capture(_cfg(), category="banana")
        assert "Unknown category" in out
        assert "data" in out  # lists valid ones

    def test_all_valid_categories_print_without_error(self):
        for cat in VALID_CATEGORIES:
            out = self._capture(_cfg(), category=cat)
            assert len(out) > 50, f"Category {cat!r} produced suspiciously short output"

    def test_no_category_arg_prints_everything(self):
        out = self._capture(_cfg(), category=None)
        assert "DATA" in out
        assert "OUTPUT" in out

    def test_capital_formatted_with_commas(self):
        cfg = _cfg(initial_capital=100_000.0)
        out = self._capture(cfg, category="period")
        assert "100,000" in out
