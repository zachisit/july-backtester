"""Output filenames built from strategy names must be Windows-legal.

Regression guard for the incident where a strategy named ``EMA_PB-A3_ADX>20``
produced output CSVs whose names contained ``>`` (illegal on Windows). Once
those files were committed, ``git checkout`` aborted on every Windows machine,
because Git fails the entire checkout when the OS rejects one path.

The fix routes every name-derived output path component -- strategy, portfolio
and symbol in ``helpers/summary.py``, the portfolio in ``main.py``'s
correlation CSV -- through the shared ``sanitize_symbol_for_filename``. These
tests pin the helpers (legal names unchanged, illegal characters gone) and each
call site that uses them.
"""
import os
from unittest.mock import patch

import pytest

from helpers.summary import _safe_strategy_name

# Characters Windows forbids in a filename component.
_ILLEGAL = set('<>:"/\\|?*')


class TestSafeStrategyName:
    def test_the_incident_name_is_made_legal(self):
        out = _safe_strategy_name("EMA_PB-A3_ADX>20")
        assert not (set(out) & _ILLEGAL), f"illegal char survived in {out!r}"
        # `>` maps to a distinct token, not a bare underscore.
        assert out == "EMA_PB-A3_ADX_gt_20"

    @pytest.mark.parametrize("name", [
        "ADX>20", "ADX<20", "ADX>=20", "ADX<=20",
        'weird:name*with?everything"|<>',
        "SMA/EMA cross", "RSI (14) mean-rev",
    ])
    def test_no_illegal_char_survives(self, name):
        assert not (set(_safe_strategy_name(name)) & _ILLEGAL)

    def test_comparison_variants_do_not_collide(self):
        # `>` and `<` must not both collapse to `_`, or ADX>20 and ADX<20 would
        # overwrite each other's output files.
        assert _safe_strategy_name("ADX>20") != _safe_strategy_name("ADX<20")

    @pytest.mark.parametrize("name,expected", [
        ("CON", "_CON"), ("CON.", "_CON."), ("()", "_EMPTY_"),
    ])
    def test_reserved_and_empty_stems_still_safe(self, name, expected):
        assert _safe_strategy_name(name) == expected

    def test_legal_names_unchanged_from_prior_behaviour(self):
        # The historical space-to-underscore and parenthesis-removal rules stay,
        # so already-legal strategy filenames do not churn.
        assert _safe_strategy_name("SMA Crossover (20/50)") == "SMA_Crossover_20_50"
        assert _safe_strategy_name("MACD Crossover") == "MACD_Crossover"


class TestSafePathComponent:
    def test_legal_names_unchanged_from_prior_behaviour(self):
        # The old `.replace(" ", "_")` output, byte for byte.
        from helpers.summary import safe_path_component
        assert safe_path_component("Nasdaq 100") == "Nasdaq_100"
        assert safe_path_component("S&P 500 PIT") == "S&P_500_PIT"
        assert safe_path_component("AAPL") == "AAPL"

    @pytest.mark.parametrize("name", ["Nasdaq: PIT", "I:SPX", "a|b", 'q"?*'])
    def test_no_illegal_char_survives(self, name):
        from helpers.summary import safe_path_component
        assert not (set(safe_path_component(name)) & _ILLEGAL)


# The tests above pin the helpers. These pin the CALL SITES: reverting either
# site in summary.py to the old hand-rolled chain fails one of them, which the
# helper tests alone would not notice.

def _result(strategy, portfolio="Nasdaq: PIT", asset="I:SPX"):
    return {
        "Strategy": strategy, "Portfolio": portfolio, "Asset": asset,
        "Trades": 1, "pnl_percent": 0.10, "max_drawdown": 0.05,
        "mc_score": 50.0, "mc_verdict": "Robust", "calmar_ratio": 1.0,
        "sharpe_ratio": 1.0, "win_rate": 1.0, "profit_factor": 2.0,
        "vs_spy_benchmark": 0.05, "vs_qqq_benchmark": 0.03,
        "avg_trade_duration": 3.0, "oos_pnl_pct": 0.02, "wfa_verdict": "Pass",
        "expectancy": 0.5, "sqn": 1.2,
        "trade_log": [{
            "EntryDate": "2024-01-02", "ExitDate": "2024-01-05",
            "EntryPrice": 100.0, "ExitPrice": 105.0, "Profit": 50.0,
            "ProfitPct": 0.05, "is_win": True, "HoldDuration": 3,
            "Shares": 10, "MAE_pct": 0.01, "MFE_pct": 0.06,
            "Symbol": "AAPL", "ExitReason": "Signal",
        }],
    }


def _illegal_paths(root):
    bad = []
    for dirpath, dirnames, filenames in os.walk(root):
        for part in dirnames + filenames:
            if set(part) & _ILLEGAL:
                bad.append(os.path.join(dirpath, part))
    return bad


class TestCallSitesWriteLegalPaths:
    def test_trailing_stem_dot_preserves_distinct_trade_and_equity_files(self, tmp_path, monkeypatch):
        import pandas as pd
        from helpers.summary import generate_per_portfolio_summary
        monkeypatch.chdir(tmp_path)
        results = [_result("RSI 2", portfolio="Nasdaq 100"),
                   _result("RSI 2.", portfolio="Nasdaq 100")]
        for result, profit in zip(results, [101., 202.]):
            result["trade_log"][0]["Profit"] = profit
            result["portfolio_timeline"] = pd.Series(
                [100000., 100000. + profit],
                index=pd.to_datetime(["2024-01-02", "2024-01-05"]))
        with patch.dict("config.CONFIG", {
                "upload_to_s3": False, "save_individual_trades": True,
                "save_only_filtered_trades": False}):
            generate_per_portfolio_summary(results, "Nasdaq 100", {}, "dots")
        root = tmp_path / "output/runs/dots"
        folder = root / "analyzer_csvs/Nasdaq_100"
        for stem, profit in [("RSI_2", 101.), ("RSI_2.", 202.)]:
            assert pd.read_csv(folder / f"{stem}.csv")["Profit"].tolist() == [profit]
            equity = pd.read_csv(folder / f"{stem}_equity.csv", index_col=0)
            assert equity.iloc[-1, 0] == 100000. + profit
            trade_path, = root.rglob(f"I_SPX_{stem}_trade_log.csv")
            assert pd.read_csv(trade_path)["Profit"].tolist() == [profit]
        assert _illegal_paths(root) == []

    def test_save_trades_to_csv(self, tmp_path):
        from helpers.summary import save_trades_to_csv
        with patch.dict("config.CONFIG", {"upload_to_s3": False}):
            save_trades_to_csv(_result("EMA_PB-A3_ADX>20"), str(tmp_path), "run")
        assert os.listdir(tmp_path) == ["I_SPX_EMA_PB-A3_ADX_gt_20_trade_log.csv"]

    def test_save_trades_to_csv_without_asset(self, tmp_path):
        """The real pipeline never sets ``Asset``, so the symbol part falls back
        to the sanitized portfolio name. Pins that default path."""
        from helpers.summary import save_trades_to_csv
        r = _result("EMA_PB-A3_ADX>20")
        del r["Asset"]
        with patch.dict("config.CONFIG", {"upload_to_s3": False}):
            save_trades_to_csv(r, str(tmp_path), "run")
        assert os.listdir(tmp_path) == ["Nasdaq__PIT_EMA_PB-A3_ADX_gt_20_trade_log.csv"]

    def test_s3_key_is_legal(self, tmp_path):
        from helpers.summary import save_trades_to_csv
        r = _result("EMA_PB-A3_ADX>20")
        del r["Asset"]
        with patch.dict("config.CONFIG", {"upload_to_s3": True,
                                          "s3_reports_bucket": "b"}), \
                patch("helpers.summary.upload_file_to_s3") as up:
            save_trades_to_csv(r, str(tmp_path), "run")
        key = up.call_args[0][2]
        assert key == "run/Nasdaq__PIT/trades/Nasdaq__PIT_EMA_PB-A3_ADX_gt_20_trade_log.csv"

    def test_main_correlation_csv_path(self):
        import main
        path = main._correlation_csv_path("run", "Nasdaq: PIT")
        assert os.path.basename(path) == "Nasdaq__PIT_strategy_correlation.csv"

    def test_main_builds_the_correlation_path_only_through_the_helper(self):
        """The helper test above cannot see main() inlining the old expression
        (QA round 2 on #404: that mutant passed 268 tests). main() is too heavy
        to drive here, so pin it structurally: the filename suffix may appear
        only inside _correlation_csv_path, and main() must call it."""
        import ast
        import inspect
        import main
        tree = ast.parse(inspect.getsource(main))
        owners = []
        for fn in ast.walk(tree):
            if isinstance(fn, ast.FunctionDef):
                for n in ast.walk(fn):
                    if (isinstance(n, ast.Constant) and isinstance(n.value, str)
                            and "_strategy_correlation.csv" in n.value):
                        owners.append(fn.name)
        assert set(owners) == {"_correlation_csv_path"}, owners
        main_fn = next(f for f in ast.walk(tree)
                       if isinstance(f, ast.FunctionDef) and f.name == "main")
        assert any(isinstance(n, ast.Call) and getattr(n.func, "id", None)
                   == "_correlation_csv_path" for n in ast.walk(main_fn))

    def test_generate_per_portfolio_summary_analyzer_csvs(self, tmp_path, monkeypatch):
        from helpers.summary import generate_per_portfolio_summary
        monkeypatch.chdir(tmp_path)
        with patch.dict("config.CONFIG", {
                "upload_to_s3": False, "save_individual_trades": True,
                "save_only_filtered_trades": False}):
            generate_per_portfolio_summary(
                portfolio_results=[_result("EMA_PB-A3_ADX>20"),
                                   _result("EMA_PB-A3_ADX<20")],
                portfolio_name="Nasdaq: PIT",
                benchmark_returns={"SPY": 0.10, "QQQ": 0.12},
                run_id="run",
            )
        written = [f for _, _, fs in os.walk(tmp_path / "output") for f in fs]
        # Both comparison variants landed as distinct files in both trees.
        assert "EMA_PB-A3_ADX_gt_20.csv" in written
        assert "EMA_PB-A3_ADX_lt_20.csv" in written
        assert "I_SPX_EMA_PB-A3_ADX_gt_20_trade_log.csv" in written
        assert _illegal_paths(tmp_path / "output") == []
