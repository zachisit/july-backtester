"""Offline scanner contracts and a frozen reconstruction of the #349 review tape."""
import io
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from scripts import pattern_scan as scan
from scripts import build_us_universe as universe

FIXTURES = Path(__file__).parent / "fixtures" / "pattern_scan"


def frame(n=300):
    return pd.DataFrame({"Open": 10., "High": 11., "Low": 9., "Close": 10.,
                         "Volume": 1e6}, index=pd.bdate_range("2010-01-04", periods=n, tz="UTC"))


@pytest.fixture(scope="module")
def frozen():
    manifest = json.loads((FIXTURES / "manifest.json").read_text())
    data = {symbol: pd.read_csv(FIXTURES / f"{symbol}.csv", index_col="Datetime", parse_dates=True)
            for symbol in manifest["symbols"]}
    return manifest, data


@pytest.mark.parametrize("symbol", ["MDLZ", "DASH", "KHC", "XEL"])
def test_frozen_review_tape_keeps_geometry_and_default_scores(frozen, symbol):
    manifest, data = frozen
    expected = manifest["detections"][symbol]
    actual = {name: detector(symbol, data[symbol], data["SPY"]["Close"], dict(scan.DEFAULT_PARAMS))
              for name, detector in scan.DETECTORS.items()}
    actual = {name: c for name, c in actual.items() if c is not None}
    assert set(actual) == set(expected)
    for name, fields in expected.items():
        for key, value in fields.items():
            assert actual[name][key] == pytest.approx(value, rel=1e-9, abs=1e-8), (symbol, name, key)
        assert actual[name]["ceiling_tolerance_source"] in {"percent", "atr", "both"}
    if symbol == "MDLZ":
        assert "rectangle" not in actual  # Whole-base floor veto must remain effective.
    if symbol == "XEL":
        assert "rectangle" in actual  # A valid lower floor must remain selectable.


def _mock_main(monkeypatch, captured, detectors=None):
    monkeypatch.setattr(scan, "load_universe", lambda _: ["AAA"])
    monkeypatch.setattr(scan, "fetch_parquet", lambda *a, **k: {"AAA": frame(), "SPY": frame()})
    monkeypatch.setattr(scan, "build_html", lambda c, m, p: captured.update(candidates=c, meta=m))
    if detectors is None:
        def detector(symbol, df, spy, params, **kwargs):
            captured.setdefault("params", []).append(dict(params))
            return None
        detectors = {name: detector for name in scan.DETECTORS}
    monkeypatch.setattr(scan, "DETECTORS", detectors)


@pytest.mark.parametrize("tf,floor,expected", [("D", 55, (55, 55)), ("D", 5, (15, 40)),
                                              ("W", 5, (10, 20))])
def test_cli_base_floor_reaches_every_family_without_loosening(monkeypatch, tf, floor, expected):
    captured = {}
    _mock_main(monkeypatch, captured)
    assert scan.main(["--timeframe", tf, "--min-base", str(floor)]) == 0
    assert len(captured["params"]) == 3
    assert {(p["base_min"], p["base_min_long"]) for p in captured["params"]} == {expected}


def test_explicit_weekly_gain_equal_to_daily_default_is_honored(monkeypatch):
    captured = {}
    _mock_main(monkeypatch, captured)
    assert scan.main(["--timeframe", "W", "--min-gain", ".12"]) == 0
    assert all(p["uptrend_min_gain"] == .12 for p in captured["params"])


def test_detectors_use_family_touch_and_tolerance_controls(monkeypatch):
    seen = []
    monkeypatch.setattr(scan, "find_ceiling", lambda *a, **k: (seen.append(k) or (None, None, None)))
    params = {**scan.DEFAULT_PARAMS, "min_adv": 0., "min_touches": 3, "min_touches_long": 5,
              "tol_pct_floor": .02, "tol_atr_mult": .9}
    for detector in scan.DETECTORS.values():
        assert detector("AAA", frame(), None, params) is None
    assert [k["min_touches"] for k in seen] == [3, 5, 5]
    assert all(k["tol_pct_floor"] == .02 and k["tol_atr_mult"] == .9 for k in seen)


def test_rectangle_floor_touch_control_reaches_actual_floor(monkeypatch):
    seen = []
    monkeypatch.setattr(scan, "find_ceiling", lambda *a, **k: (20., [30, 70], {"source": "atr", "tolerance": .3}))
    monkeypatch.setattr(scan, "find_floor", lambda *a, **k: (seen.append(k) or None))
    assert scan.detect_rectangle("AAA", frame(), None,
                                 {**scan.DEFAULT_PARAMS, "min_adv": 0., "floor_min_touches": 7}) is None
    assert seen[0]["min_touches"] == 7


@pytest.mark.parametrize("atr,source,tolerance", [(.5, "atr", .3), (.05, "percent", .132)])
def test_winning_boundary_records_actual_tolerance(atr, source, tolerance):
    df = frame(50)
    level, touches, details = scan.find_ceiling(
        df, [5, 20, 35], np.full(50, atr), return_details=True)
    assert level == 11. and touches == [5, 20, 35]
    assert details["source"] == source
    assert details["tolerance"] == pytest.approx(tolerance)


def test_replay_slices_before_lookback_and_retains_timezone(tmp_path):
    data = frame(1600)
    data.to_parquet(tmp_path / "AAA.parquet")
    cutoff = data.index[400]
    result = scan.fetch_parquet(["AAA"], lookback_bars=300, as_of=str(cutoff.date()), parquet_dir=tmp_path)
    assert len(result["AAA"]) == 300
    assert result["AAA"].index[-1] == cutoff
    assert result["AAA"].index[0] == data.index[101]


def test_corrupt_symbol_does_not_abort_other_data(tmp_path):
    frame().to_parquet(tmp_path / "AAA.parquet")
    (tmp_path / "BAD.parquet").write_bytes(b"not parquet")
    errors = {}
    result = scan.fetch_parquet(["AAA", "BAD"], parquet_dir=tmp_path, errors=errors)
    assert set(result) == {"AAA"} and "BAD" in errors


def test_yahoo_replay_requests_historical_dates_and_single_symbol_frame(monkeypatch):
    calls = []
    def download(tickers, **kwargs):
        calls.append(kwargs)
        return frame()
    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(download=download))
    assert set(scan.fetch_yahoo(["AAA"], period="3y", as_of="2011-07-01")) == {"AAA"}
    assert calls[0]["start"] == "2008-07-01" and calls[0]["end"] == "2011-07-02"
    assert "period" not in calls[0]
    assert scan.fetch_yahoo(["AAA", "BBB"]) == {}  # Never assign one ambiguous frame to two companies.


def test_all_detector_errors_return_failure_with_visible_counts(monkeypatch):
    captured = {}
    def broken(*a, **k):
        raise ValueError("broken detector")
    _mock_main(monkeypatch, captured, {"rectangle": broken})
    assert scan.main([]) == 2
    assert captured["meta"]["counts"]["detection_errors"] == 1


def test_user_requested_spy_is_not_removed_as_benchmark(monkeypatch):
    captured = {}
    _mock_main(monkeypatch, captured)
    monkeypatch.setattr(scan, "load_universe", lambda _: ["SPY"])
    assert scan.main([]) == 0
    assert captured["meta"]["n_loaded"] == 1


@pytest.mark.parametrize("args", [["--min-base", "0"], ["--top", "0"], ["--max-dist", "0"],
                                 ["--min-adv", "nan"], ["--patterns", ""], ["--as-of", "20260702"]])
def test_invalid_cli_inputs_fail_before_loading(args):
    with pytest.raises(SystemExit) as exc:
        scan.main(args)
    assert exc.value.code == 2


def test_empty_and_unsafe_universes_are_rejected():
    for value in ([], {}, ["../secret"], ["AAA", 3]):
        with pytest.raises(ValueError):
            scan._validated_symbols(value)


def test_html_handles_plain_filename_escapes_inputs_and_keeps_failed_chart(monkeypatch, tmp_path, frozen):
    _, data = frozen
    candidate = scan.detect_rectangle("DASH", data["DASH"], data["SPY"]["Close"], dict(scan.DEFAULT_PARAMS))
    candidate["symbol"] = '<script>alert(1)</script>'
    monkeypatch.setattr(scan, "render_chart", lambda _: (_ for _ in ()).throw(ValueError("bad chart")))
    monkeypatch.chdir(tmp_path)
    meta = {"pattern": "rectangle", "date": "2026-07-02", "universe": "<img src=x>",
            "n_universe": 1, "n_loaded": 1, "source": "parquet", "data_end": "2026-07-02",
            "min_adv": 0., "funnel": "1 matched"}
    scan.build_html([candidate], meta, "scan.html")
    html = (tmp_path / "scan.html").read_text()
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "<img src=x>" not in html
    assert "Chart unavailable" in html and meta["chart_errors"] == 1


def test_finviz_credentials_are_not_in_report_label():
    label = scan._universe_label("https://elite.finviz.com/export.ashx?f=geo_usa&auth=secret-token")
    assert label == "finviz:geo_usa" and "secret" not in label


def test_listing_suffix_rules_are_exchange_specific_and_footer_is_ignored(monkeypatch):
    nasdaq = "Symbol|ETF|Test Issue\nABCDW|N|N\nAAPL|N|N\nFile Creation Time: 2026|N|N\n"
    other = "ACT Symbol|ETF\nABCDW|N\nOTHER|N\n"
    monkeypatch.setattr(universe.urllib.request, "urlopen", lambda url, **k: io.BytesIO(
        (nasdaq if url == universe.NASDAQ_URL else other).encode()))
    assert universe.fetch_listings() == ["AAPL", "ABCDW", "OTHER"]


def test_failed_liquidity_download_does_not_overwrite_existing_universe(monkeypatch, tmp_path):
    path = tmp_path / "universe.json"
    path.write_text('["KEEP"]')
    monkeypatch.setattr(universe, "fetch_listings", lambda: ["AAA"])
    monkeypatch.setattr(universe, "liquidity_filter", lambda *a, **k: {})
    with pytest.raises(SystemExit):
        universe.main(["--out", str(path)])
    assert path.read_text() == '["KEEP"]'


def test_real_cli_replays_frozen_bars_and_exports_provenance(tmp_path, frozen):
    _, data = frozen
    for symbol, df in data.items():
        df.to_parquet(tmp_path / f"{symbol}.parquet")
    html, artifact = tmp_path / "scan.html", tmp_path / "scan.json"
    result = subprocess.run(
        [sys.executable, str(Path(scan.__file__)), "--universe", "DASH,KHC,MDLZ,XEL",
         "--parquet-dir", str(tmp_path), "--as-of", "2026-07-02", "--out", str(html), "--json-out", str(artifact)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(artifact.read_text())
    assert payload["meta"]["counts"]["loaded"] == 4
    assert len(payload["candidates"]) == 4 and all("df" not in c for c in payload["candidates"])
    assert all(c["data_end"] == "2026-07-02" and "ceiling_tolerance_source" in c for c in payload["candidates"])
    assert '<img src="data:image/png;base64,' in html.read_text()


def test_every_detector_uses_the_shared_preamble(monkeypatch):
    calls = []
    monkeypatch.setattr(scan, "_common_gates", lambda *a: (calls.append(a) or None))
    for detector in scan.DETECTORS.values():
        assert detector("AAA", frame(), None, dict(scan.DEFAULT_PARAMS)) is None
    assert len(calls) == 3


def test_liquidity_floor_uses_twenty_sessions(monkeypatch):
    df = frame(25)
    df.iloc[:5, df.columns.get_loc("Volume")] = 100e6
    raw = pd.concat({"AAA": df}, axis=1)
    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(download=lambda *a, **k: raw))
    stats = {}
    assert universe.liquidity_filter(["AAA"], 20e6, stats=stats) == {}
    assert stats["scored"] == 1


def test_pine_confirm_alert_tracks_the_displayed_input_level():
    source = Path(scan.__file__).with_name("pattern_levels.pine").read_text()
    assert "ta.crossover(close, confirm)" in source
    assert "ta.crossover(close, B * (1 + 3.0 / 100))" not in source
