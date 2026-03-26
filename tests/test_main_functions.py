"""
Tests for main.py — covers:
  - init_worker: globals are assigned correctly
  - run_single_simulation: result=None, empty trade_pnl_list, exception path,
    no-trades branch, few-trades branch
  - main(): --init early return, polygon API key guard (S1),
    config validation errors (S2)
"""
import sys
import os
import pytest
import pandas as pd
import numpy as np
from unittest.mock import patch

import main as main_module
from main import init_worker, run_single_simulation


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_df(n=5):
    """Minimal OHLCV DataFrame for portfolio_data_global."""
    return pd.DataFrame(
        {"Open": np.linspace(99, 109, n),
         "High": np.linspace(101, 111, n),
         "Low":  np.linspace(98, 108, n),
         "Close": np.linspace(100, 110, n),
         "Volume": [1_000_000] * n,
         "Signal": [0] * n},
        index=pd.date_range("2020-01-01", periods=n, freq="B"),
    )


def _make_sim_args(stop_config=None, logic_func=None, strategy_params=None):
    """Build a valid 11-element args tuple for run_single_simulation."""
    if stop_config is None:
        stop_config = {"type": "none"}
    if logic_func is None:
        logic_func = lambda df, **kw: df.assign(Signal=0)
    return (
        "TestPortfolio",   # portfolio_name
        "TestStrategy",    # name
        logic_func,        # logic_func
        [],                # dependencies
        stop_config,       # stop_config
        0.10,              # spy_buy_and_hold_return
        0.12,              # qqq_buy_and_hold_return
        strategy_params,   # strategy_params (None OK)
        None,              # wfa_split_date
        "2020-01-01",      # spy_actual_start
        "2023-01-01",      # spy_actual_end
    )


def _valid_cfg(**overrides):
    """
    Minimal config dict that bypasses both S1 (API key, uses csv provider)
    and S2 (config validation) checks inside main().
    """
    base = {
        "data_provider": "csv",
        "start_date": "2020-01-01",
        "end_date": "2023-01-01",
        "allocation_per_trade": 0.1,
        "portfolios": {"Test": ["AAPL"]},
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# init_worker — sets multiprocessing globals
# ---------------------------------------------------------------------------

class TestInitWorker:

    def test_sets_spy_global(self):
        spy = pd.DataFrame({"Close": [100.0]})
        init_worker(spy, None, None, {})
        assert main_module.spy_df_global is spy

    def test_sets_vix_global(self):
        vix = pd.DataFrame({"Close": [20.0]})
        init_worker(None, vix, None, {})
        assert main_module.vix_df_global is vix

    def test_sets_tnx_global(self):
        tnx = pd.DataFrame({"Close": [3.5]})
        init_worker(None, None, tnx, {})
        assert main_module.tnx_df_global is tnx

    def test_sets_portfolio_data_global(self):
        data = {"AAPL": _make_df(), "MSFT": _make_df()}
        init_worker(None, None, None, data)
        assert main_module.portfolio_data_global is data

    def test_all_globals_set_in_one_call(self):
        spy = pd.DataFrame({"Close": [100.0]})
        vix = pd.DataFrame({"Close": [18.0]})
        tnx = pd.DataFrame({"Close": [4.0]})
        data = {"AAPL": _make_df()}
        init_worker(spy, vix, tnx, data)
        assert main_module.spy_df_global is spy
        assert main_module.vix_df_global is vix
        assert main_module.tnx_df_global is tnx
        assert main_module.portfolio_data_global is data


# ---------------------------------------------------------------------------
# run_single_simulation — guard clauses
# ---------------------------------------------------------------------------

class TestRunSingleSimulationGuards:

    def setup_method(self):
        """Populate global portfolio data before each test."""
        init_worker(None, None, None, {"AAPL": _make_df()})

    def test_run_portfolio_simulation_returns_none_propagates(self):
        """If run_portfolio_simulation returns None, the worker returns None."""
        args = _make_sim_args()
        with patch("main.run_portfolio_simulation", return_value=None):
            assert run_single_simulation(args) is None

    def test_empty_trade_pnl_list_falls_through_to_none(self):
        """
        result is not None but trade_pnl_list is empty — the outer
        `if result and result.get('trade_pnl_list')` is False, so the
        function falls through and implicitly returns None.
        """
        args = _make_sim_args()
        with patch("main.run_portfolio_simulation",
                   return_value={"trade_pnl_list": []}):
            assert run_single_simulation(args) is None

    def test_exception_in_logic_func_returns_none(self):
        """An exception inside the strategy logic is caught and None is returned."""
        def exploding_logic(df, **kw):
            raise RuntimeError("strategy exploded")

        args = _make_sim_args(logic_func=exploding_logic)
        assert run_single_simulation(args) is None

    def test_exception_in_run_portfolio_simulation_returns_none(self):
        """An exception inside run_portfolio_simulation is caught and None returned."""
        args = _make_sim_args()
        with patch("main.run_portfolio_simulation",
                   side_effect=ValueError("simulation failed")):
            assert run_single_simulation(args) is None


# ---------------------------------------------------------------------------
# run_single_simulation — mc_verdict branches
# ---------------------------------------------------------------------------

class TestRunSingleSimulationMcBranches:

    def setup_method(self):
        init_worker(None, None, None, {"AAPL": _make_df()})

    def _base_result(self, trades, pnl_list=None):
        return {
            "trade_pnl_list": pnl_list if pnl_list is not None else [0.01] * max(trades, 1),
            "Trades": trades,
            "pnl_percent": 0.05,
            "trade_log": [],
        }

    def test_no_trades_sets_mc_verdict_na(self):
        """Trades == 0 → mc_verdict = 'N/A (no trades)', mc_score = -999."""
        args = _make_sim_args()
        with patch("main.run_portfolio_simulation",
                   return_value=self._base_result(0)):
            result = run_single_simulation(args)
        assert result is not None
        assert result["mc_verdict"] == "N/A (no trades)"
        assert result["mc_score"] == -999

    def test_no_trades_sets_zero_metrics(self):
        """Zero-trade results should have 0 for max_drawdown, sharpe_ratio etc."""
        args = _make_sim_args()
        with patch("main.run_portfolio_simulation",
                   return_value=self._base_result(0)):
            result = run_single_simulation(args)
        assert result["max_drawdown"] == 0
        assert result["sharpe_ratio"] == 0
        assert result["win_rate"] == 0

    def test_few_trades_sets_mc_verdict_few_trades(self):
        """
        Trades > 0 but < min_trades_for_mc (default 50 in config) → 'N/A (few trades)'.
        Using 3 trades to be safely below any reasonable threshold.
        """
        args = _make_sim_args()
        with patch("main.run_portfolio_simulation",
                   return_value=self._base_result(3)):
            result = run_single_simulation(args)
        assert result is not None
        assert result["mc_verdict"] == "N/A (few trades)"
        assert result["mc_score"] == -999

    def test_benchmark_comparison_computed(self):
        """vs_spy_benchmark and vs_qqq_benchmark are set based on pnl_percent."""
        args = _make_sim_args()   # spy=0.10, qqq=0.12
        with patch("main.run_portfolio_simulation",
                   return_value=self._base_result(0)):
            result = run_single_simulation(args)
        assert pytest.approx(result["vs_spy_benchmark"]) == 0.05 - 0.10
        assert pytest.approx(result["vs_qqq_benchmark"]) == 0.05 - 0.12

    def test_wfa_verdict_na_when_no_split_date(self):
        """wfa_split_date=None → wfa_verdict = 'N/A'."""
        args = _make_sim_args()
        with patch("main.run_portfolio_simulation",
                   return_value=self._base_result(0)):
            result = run_single_simulation(args)
        assert result["wfa_verdict"] == "N/A"

    def test_rolling_wfa_verdict_na_when_wfa_folds_none(self):
        """wfa_folds=None in CONFIG → wfa_rolling_verdict = 'N/A'."""
        args = _make_sim_args()
        with patch("main.run_portfolio_simulation",
                   return_value=self._base_result(0)), \
             patch.dict("config.CONFIG", {"wfa_folds": None}):
            result = run_single_simulation(args)
        assert result["wfa_rolling_verdict"] == "N/A"


# ---------------------------------------------------------------------------
# main() — --init early return
# ---------------------------------------------------------------------------

class TestMainInitFlag:

    def test_init_flag_calls_run_init_wizard(self):
        with patch("sys.argv", ["main.py", "--init"]), \
             patch("helpers.init_wizard.run_init_wizard") as mock_wizard:
            main_module.main()
        mock_wizard.assert_called_once()

    def test_init_flag_returns_normally_without_system_exit(self):
        """--init returns after wizard; it must NOT call sys.exit."""
        with patch("sys.argv", ["main.py", "--init"]), \
             patch("helpers.init_wizard.run_init_wizard"):
            main_module.main()  # should not raise SystemExit


# ---------------------------------------------------------------------------
# main() — S1: Polygon API key guard
# ---------------------------------------------------------------------------

class TestMainApiKeyGuard:

    def _env_without_polygon_key(self):
        return {k: v for k, v in os.environ.items() if k != "POLYGON_API_KEY"}

    def test_polygon_missing_key_exits_1(self):
        # load_dotenv() inside main() would restore the key from .env — mock it out.
        with patch("sys.argv", ["main.py"]), \
             patch.dict("config.CONFIG", _valid_cfg(data_provider="polygon")), \
             patch.dict("os.environ", self._env_without_polygon_key(), clear=True), \
             patch("dotenv.load_dotenv"):
            with pytest.raises(SystemExit) as exc_info:
                main_module.main()
        assert exc_info.value.code == 1

    def test_polygon_empty_string_key_exits_1(self):
        """Empty string is falsy — treated same as missing key."""
        with patch("sys.argv", ["main.py"]), \
             patch.dict("config.CONFIG", _valid_cfg(data_provider="polygon")), \
             patch.dict("os.environ", {"POLYGON_API_KEY": ""}), \
             patch("dotenv.load_dotenv"):
            with pytest.raises(SystemExit) as exc_info:
                main_module.main()
        assert exc_info.value.code == 1

    def test_csv_provider_bypasses_api_key_check(self):
        """
        Non-polygon provider should NOT exit due to missing POLYGON_API_KEY.
        The function will exit at S2 config validation (bad dates trigger that).
        """
        env = self._env_without_polygon_key()
        with patch("sys.argv", ["main.py"]), \
             patch.dict("config.CONFIG", _valid_cfg(
                 data_provider="csv",
                 start_date="2023-01-01",
                 end_date="2020-01-01",   # end before start → S2 error
             )), \
             patch.dict("os.environ", env, clear=True):
            with pytest.raises(SystemExit) as exc_info:
                main_module.main()
        # Code 1 comes from S2 config validation, not S1 API key check
        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# main() — S2: Config validation errors
# ---------------------------------------------------------------------------

class TestMainConfigValidation:

    def test_bad_start_date_format_exits_1(self):
        with patch("sys.argv", ["main.py"]), \
             patch.dict("config.CONFIG", _valid_cfg(start_date="not-a-date")):
            with pytest.raises(SystemExit) as exc_info:
                main_module.main()
        assert exc_info.value.code == 1

    def test_start_equals_end_exits_1(self):
        with patch("sys.argv", ["main.py"]), \
             patch.dict("config.CONFIG", _valid_cfg(
                 start_date="2020-06-01", end_date="2020-06-01"
             )):
            with pytest.raises(SystemExit) as exc_info:
                main_module.main()
        assert exc_info.value.code == 1

    def test_start_after_end_exits_1(self):
        with patch("sys.argv", ["main.py"]), \
             patch.dict("config.CONFIG", _valid_cfg(
                 start_date="2023-01-01", end_date="2020-01-01"
             )):
            with pytest.raises(SystemExit) as exc_info:
                main_module.main()
        assert exc_info.value.code == 1

    def test_allocation_zero_exits_1(self):
        with patch("sys.argv", ["main.py"]), \
             patch.dict("config.CONFIG", _valid_cfg(allocation_per_trade=0)):
            with pytest.raises(SystemExit) as exc_info:
                main_module.main()
        assert exc_info.value.code == 1

    def test_allocation_above_one_exits_1(self):
        with patch("sys.argv", ["main.py"]), \
             patch.dict("config.CONFIG", _valid_cfg(allocation_per_trade=1.5)):
            with pytest.raises(SystemExit) as exc_info:
                main_module.main()
        assert exc_info.value.code == 1

    def test_allocation_negative_exits_1(self):
        with patch("sys.argv", ["main.py"]), \
             patch.dict("config.CONFIG", _valid_cfg(allocation_per_trade=-0.1)):
            with pytest.raises(SystemExit) as exc_info:
                main_module.main()
        assert exc_info.value.code == 1

    def test_empty_portfolios_and_no_symbols_exits_1(self):
        with patch("sys.argv", ["main.py"]), \
             patch.dict("config.CONFIG", _valid_cfg(
                 portfolios={}, symbols_to_test=[]
             )):
            with pytest.raises(SystemExit) as exc_info:
                main_module.main()
        assert exc_info.value.code == 1

    def test_none_portfolios_and_no_symbols_exits_1(self):
        with patch("sys.argv", ["main.py"]), \
             patch.dict("config.CONFIG", _valid_cfg(
                 portfolios=None, symbols_to_test=None
             )):
            with pytest.raises(SystemExit) as exc_info:
                main_module.main()
        assert exc_info.value.code == 1
