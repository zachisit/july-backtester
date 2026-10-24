"""Delta-runner call contract and private-strategy source classification.

The report it writes is committed to the PUBLIC repo with --hide-private, so a
mistag publishes a private strategy's name. The first version tagged by module
name, which load_strategies derives from the folder name -- a private folder
not literally called "private" was tagged public (adversarial QA on #405).
"""
import importlib.util
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _script():
    spec = importlib.util.spec_from_file_location(
        "entry_trigger_delta", os.path.join(ROOT, "scripts", "entry_trigger_delta.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _logic_from(path):
    spec = importlib.util.spec_from_file_location("secret_strats.dummy", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return {"logic": mod.dummy}


def test_a_private_folder_with_any_name_is_private(tmp_path):
    d = tmp_path / "secret_strats"
    d.mkdir()
    (d / "dummy.py").write_text("def dummy(df, **kw):\n    return df\n")
    meta = _logic_from(str(d / "dummy.py"))
    D = _script()
    assert D.is_private(meta, [str(d)])
    assert not D.is_private(meta, [str(tmp_path / "elsewhere")])


def test_a_public_plugin_is_public():
    D = _script()
    from custom_strategies import sma_crossovers  # noqa: F401  (registers)
    from helpers.registry import get_active_strategies
    strats = get_active_strategies(os.path.join(ROOT, "custom_strategies"))
    meta = next(m for m in strats.values()
                if m["logic"].__module__.endswith("sma_crossovers"))
    assert not D.is_private(meta, [os.path.join(ROOT, "custom_strategies", "private")])


def test_no_findable_source_is_private_not_public():
    """A callable with no source file (a functools.partial, a C builtin)
    resolved to the CWD and was tagged PUBLIC. Unknown origin must never be
    printed under --hide-private."""
    import functools
    D = _script()
    meta = {"logic": functools.partial(len)}
    assert D.is_private(meta, [os.path.join(ROOT, "custom_strategies", "private")])


def test_load_strats_restores_the_strategies_filter():
    import config as C
    D = _script()
    before = C.CONFIG.get("strategies", "all")
    C.CONFIG["strategies"] = ["Some Subset"]
    try:
        D.load_strats(None)
        assert C.CONFIG["strategies"] == ["Some Subset"]
    finally:
        C.CONFIG["strategies"] = before


def test_ticker_dependent_signals_cover_each_symbol_and_report_real_failures():
    import pandas as pd
    D = _script()
    dates = pd.date_range("2024-01-02", periods=3)
    data = {s: pd.DataFrame({"Close": [10., 11., 12.]}, index=dates)
            for s in ("AAA", "BBB", "BROKEN")}

    def logic(df, **kwargs):
        symbol = kwargs["symbol"]
        if symbol == "BROKEN":
            raise ValueError("unavailable events")
        df["Signal"] = [1, 0, -1] if symbol == "AAA" else [0, 1, -1]
        return df

    signals, failed = D.signals_for({"logic": logic}, data, None, None)
    assert failed == ["BROKEN:ValueError"]
    assert set(signals) == {"AAA", "BBB"}
    assert signals["AAA"].tolist() == [1, 0, -1]
    assert signals["BBB"].tolist() == [0, 1, -1]
    assert all("Signal" not in df for df in data.values())


def test_strategy_params_override_injected_kwargs_like_the_pipeline():
    import pandas as pd
    D = _script()
    frame = pd.DataFrame({"Close": [10.]})

    def logic(df, **kwargs):
        assert kwargs["symbol"] == "OVERRIDE"
        assert kwargs["spy_df"] == "custom benchmark"
        return pd.Series([1], index=df.index)

    meta = {"logic": logic, "dependencies": ["spy"],
            "params": {"symbol": "OVERRIDE", "spy_df": "custom benchmark"}}
    signals, failed = D.signals_for(meta, {"AAA": frame}, frame, None)
    assert failed == []
    assert signals["AAA"].tolist() == [1]


@pytest.mark.parametrize("hide_private", [True, False])
def test_private_plugin_diagnostics_respect_the_report_mode(
        monkeypatch, capsys, hide_private):
    """Imports, signals and simulations can all print or log private names."""
    import logging
    import sys
    import pandas as pd

    D = _script()
    secret = "PRIVATE_STRATEGY_SENTINEL"
    frame = pd.DataFrame({"Close": [10., 11., 12.]},
                         index=pd.date_range("2024-01-02", periods=3))
    stages = []
    log = logging.getLogger("delta_private_probe")
    # Bind before the script redirects stderr, as an existing handler would.
    handler = logging.StreamHandler(sys.stderr)
    log.addHandler(handler)
    disabled_before = logging.root.manager.disable

    def emit(stage):
        stages.append(stage)
        print(f"{secret} {stage} stdout")
        print(f"{secret} {stage} stderr", file=sys.stderr)
        log.warning("%s %s log", secret, stage)

    def logic(df, **kwargs):
        emit("signal")
        return pd.Series([1, 0, -1], index=df.index)

    def load_strats(_):
        emit("import")
        return {secret: {"logic": logic}}

    def count_trades(mode, *args):
        emit(mode)
        return 1

    monkeypatch.setattr(D, "SYMS", ["AAA"])
    monkeypatch.setattr(D, "load", lambda *args: frame)
    monkeypatch.setattr(D, "load_strats", load_strats)
    monkeypatch.setattr(D, "is_private", lambda *args: True)
    monkeypatch.setattr(D, "count_trades", count_trades)
    monkeypatch.setattr(sys, "argv", ["delta"] +
                        (["--hide-private"] if hide_private else []))
    try:
        D.main()
    finally:
        log.removeHandler(handler)
    captured = capsys.readouterr()
    assert stages == ["import", "signal", "level", "edge"]
    assert logging.root.manager.disable == disabled_before
    if hide_private:
        assert secret not in captured.out + captured.err
        assert "TOTAL (private only)" in captured.out
        assert "[1/1]" in captured.err
    else:
        for stage in stages:
            assert f"{secret} {stage} stdout" in captured.out
            assert f"{secret} {stage} stderr" in captured.err
            assert f"{secret} {stage} log" in captured.err


def test_load_strats_restores_filter_when_discovery_fails(monkeypatch):
    import config as C
    import helpers.registry as registry

    D = _script()
    monkeypatch.setitem(C.CONFIG, "strategies", ["Some Subset"])

    def fail(*args):
        raise RuntimeError("discovery failed")

    monkeypatch.setattr(registry, "get_active_strategies", fail)
    with pytest.raises(RuntimeError, match="discovery failed"):
        D.load_strats(None)
    assert C.CONFIG["strategies"] == ["Some Subset"]
