"""Tests for portable resolution + graceful fallback of ``intrabar_parquet_source``.

Previously the intrabar feature depended on a contributor-local absolute path
(a Windows `C:\\Users\\...` parquet) that silently disabled sub-bar resolution
on any other machine. `_resolve_intrabar_source` now makes the path portable
(`~`/`$ENV`/repo-relative), and `_build_intrabar_data` falls back to the normal
per-symbol data provider when the file is absent instead of no-opping.
"""
import os
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

import main
from main import _resolve_intrabar_source, _build_intrabar_data

_PROJECT_ROOT = os.path.dirname(os.path.abspath(main.__file__))


class TestResolveIntrabarSource:
    def test_absolute_path_unchanged(self):
        p = "/tmp/nq_1min.parquet" if os.name != "nt" else "C:\\data\\nq.parquet"
        assert _resolve_intrabar_source(p) == p

    def test_relative_path_resolved_against_project_root(self):
        resolved = _resolve_intrabar_source("data/nq_1min.parquet")
        assert os.path.isabs(resolved)
        assert resolved == os.path.join(_PROJECT_ROOT, "data/nq_1min.parquet")

    def test_tilde_expanded(self):
        resolved = _resolve_intrabar_source("~/nq_1min.parquet")
        assert "~" not in resolved
        # normpath so the comparison is separator-agnostic: expanduser keeps the
        # input's "/" on Windows while os.path.join emits "\".
        assert os.path.normpath(resolved) == os.path.normpath(
            os.path.join(os.path.expanduser("~"), "nq_1min.parquet"))

    def test_env_var_expanded(self, monkeypatch, tmp_path):
        # Use an OS-native absolute dir: a POSIX "/data/..." path is not absolute
        # on Windows, so _resolve_intrabar_source would prepend the project drive.
        monkeypatch.setenv("MY_INTRABAR_DIR", str(tmp_path))
        resolved = _resolve_intrabar_source("$MY_INTRABAR_DIR/nq.parquet")
        assert os.path.normpath(resolved) == os.path.normpath(
            os.path.join(str(tmp_path), "nq.parquet"))


class TestBuildIntrabarDataFallback:
    def test_missing_source_falls_back_to_provider(self, caplog):
        # A configured-but-missing parquet must NOT no-op — it should fall
        # through to the per-symbol provider fetch.
        fetcher = MagicMock(return_value=None)  # provider serves nothing -> {}
        cfg = {
            "intrabar_parquet_source": "/definitely/not/here/nq_1min.parquet",
            "start_date": "2020-01-01", "end_date": "2020-02-01",
            "intrabar_timeframe": "MIN", "intrabar_multiplier": 1,
        }
        with patch.object(main, "get_data_service", return_value=fetcher):
            out = _build_intrabar_data({"AAPL": pd.DataFrame()}, cfg)
        # Fell through to the provider path (fetcher consulted for the symbol)
        fetcher.assert_called_once()
        assert fetcher.call_args[0][0] == "AAPL"
        assert out == {}
        assert any("not found" in r.message and "falling back" in r.message
                   for r in caplog.records)

    def test_no_source_uses_provider(self):
        fetcher = MagicMock(return_value=None)
        cfg = {"start_date": "2020-01-01", "end_date": "2020-02-01",
               "intrabar_timeframe": "MIN", "intrabar_multiplier": 1}
        with patch.object(main, "get_data_service", return_value=fetcher):
            out = _build_intrabar_data({"AAPL": pd.DataFrame()}, cfg)
        fetcher.assert_called_once()
        assert out == {}

    def test_existing_parquet_is_loaded(self, tmp_path):
        pytest.importorskip("pyarrow")
        idx = pd.date_range("2020-01-02 09:30", periods=5, freq="min")
        src = tmp_path / "nq_1min.parquet"
        pd.DataFrame(
            {"open": range(5), "high": range(5), "low": range(5), "close": range(5)},
            index=idx,
        ).to_parquet(src)
        cfg = {"intrabar_parquet_source": str(src)}
        out = _build_intrabar_data({"NQZ5": pd.DataFrame()}, cfg)
        assert "NQZ5" in out
        assert list(out["NQZ5"].columns) == ["Open", "High", "Low", "Close"]
        assert len(out["NQZ5"]) == 5
