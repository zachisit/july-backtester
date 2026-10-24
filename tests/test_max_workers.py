"""#414: cap the simulation pool so wide universes don't OOM.

Every worker gets its own copy of portfolio_data through init_worker, so peak
memory is ~(workers + 1) x portfolio_data. ``max_workers`` / ``--workers``
bounds the pool; the default (None) must keep min(cpu_count(), tasks).
"""
import ast
from pathlib import Path

import pandas as pd
import pytest

import main
from config import CONFIG
from helpers.cli_config import VALID_CATEGORIES, _SECTIONS, apply_overrides, build_parser
from helpers.config_validator import KNOWN_KEYS, validate_config


@pytest.fixture
def eight_cpus(monkeypatch):
    monkeypatch.setattr(main, "cpu_count", lambda: 8)


class TestPoolSize:
    def test_default_is_unchanged(self, eight_cpus):
        assert main._pool_size(4) == 4            # tasks < cpus
        assert main._pool_size(20) == 8           # cpus < tasks
        assert main._pool_size(4, None) == 4

    def test_cap_bounds_the_pool(self, eight_cpus):
        assert main._pool_size(4, 1) == 1         # --workers 1: serial, one invocation
        assert main._pool_size(20, 3) == 3
        assert main._pool_size(2, 6) == 2         # never more workers than tasks

    @pytest.mark.parametrize("bad", [0, -2, "2", 1.5, True])
    def test_invalid_cap_is_ignored(self, eight_cpus, bad):
        assert main._pool_size(4, bad) == 4

    def test_pool_is_built_from_the_capped_size(self):
        """The Pool's `processes=` must be the _pool_size result fed max_workers."""
        tree = ast.parse(Path(main.__file__).read_text(encoding="utf-8"))
        assigns = [n for n in ast.walk(tree)
                   if isinstance(n, ast.Assign) and any(getattr(t, "id", None) == "_n_workers" for t in n.targets)]
        assert assigns, "_n_workers assignment not found"
        call = assigns[0].value
        assert isinstance(call, ast.Call) and getattr(call.func, "id", None) == "_pool_size"
        assert "max_workers" in ast.unparse(call)
        pools = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "Pool"]
        assert any(ast.unparse(kw.value) == "_n_workers" for p in pools for kw in p.keywords if kw.arg == "processes")


class TestConfigSurface:
    def test_default_is_none(self):
        assert "max_workers" in CONFIG and CONFIG["max_workers"] is None

    def test_known_key(self):
        assert "max_workers" in KNOWN_KEYS
        assert not any("max_workers" in w for w in validate_config({"max_workers": 2}))

    @pytest.mark.parametrize("bad", [0, -1, "4", 2.5, True])
    def test_invalid_value_warns(self, bad):
        assert any("max_workers" in w for w in validate_config({"max_workers": bad}))

    def test_cli_flag_sets_the_key(self):
        cfg = apply_overrides({"max_workers": None}, build_parser().parse_args(["--workers", "1"]))
        assert cfg["max_workers"] == 1

    def test_cli_flag_absent_leaves_config_alone(self):
        cfg = apply_overrides({"max_workers": 3}, build_parser().parse_args([]))
        assert cfg["max_workers"] == 3

    def test_in_help_config(self):
        keys = [e["config_key"] for _, _, entries in _SECTIONS for e in entries]
        assert "max_workers" in keys


def test_portfolio_data_mb_estimate():
    df = pd.DataFrame({"Close": [1.0] * 1_000, "Volume": [2.0] * 1_000},
                      index=pd.date_range("2020-01-01", periods=1_000))
    mb = main._portfolio_data_mb({"A": df, "B": df})
    assert mb is not None and 0.03 < mb < 0.06            # 2 x (8 KB index + 16 KB data)
    assert main._portfolio_data_mb(None) is None          # never raises
