"""Regression tests for the 2026-06-06 pipeline issue-batch fixes:

- UnifiedMarketDataProvider: raw-price execution API, date-suffixed/share-class
  resolution.
- merge.merge_delisted: deterministic collision naming.
- audit.index_validation: blocking index semantic gate + value bounds.
- pit_enforcement: membership-span trim.
- point_in_time: expanded alias map.

All synthetic (tmp_path / monkeypatch) — no dependency on the 2.8GB merged store.
"""
import json
import os
import sys
from unittest.mock import patch

import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.data.pipeline import paths, merge, audit
from src.data.unified_market_data_provider import UnifiedMarketDataProvider


def _write_merged(d, name, last_close, factor=1.0, source="polygon",
                  sec_type="CS", n=10, start="2026-01-01", status="ok"):
    idx = pd.date_range(start, periods=n, freq="D")
    df = pd.DataFrame({
        "open": last_close, "high": last_close, "low": last_close,
        "close": [last_close] * n, "volume": 1000.0, "vwap": float("nan"),
        "source": source, "security_type": sec_type,
        "adjustment_factor": factor, "adjustment_method": "none",
        "data_quality_status": status,
    }, index=idx)
    df.to_parquet(os.path.join(d, f"{name}.parquet"))
    return df


# ----------------------------------------------------------------- provider ---
class TestRawPriceApi:
    def test_raw_is_canonical_over_factor(self, tmp_path):
        _write_merged(tmp_path, "ZZ", last_close=500.0, factor=5.0)
        p = UnifiedMarketDataProvider(merged_dir=str(tmp_path))
        can = p.get_price_data("ZZ")
        raw = p.get_raw_price_data("ZZ")
        assert can["Close"].iloc[-1] == pytest.approx(500.0)
        assert raw["Close"].iloc[-1] == pytest.approx(100.0)   # 500 / 5

    def test_execution_price_scalar(self, tmp_path):
        _write_merged(tmp_path, "ZZ", last_close=500.0, factor=5.0)
        p = UnifiedMarketDataProvider(merged_dir=str(tmp_path))
        assert p.get_execution_price("ZZ", "2026-12-31") == pytest.approx(100.0)

    def test_factor_one_raw_equals_canonical(self, tmp_path):
        _write_merged(tmp_path, "ZZ", last_close=42.0, factor=1.0)
        p = UnifiedMarketDataProvider(merged_dir=str(tmp_path))
        assert (p.get_raw_price_data("ZZ")["Close"].iloc[-1]
                == pytest.approx(p.get_price_data("ZZ")["Close"].iloc[-1]))


class TestResolution:
    def test_date_suffixed_delisted_resolves(self, tmp_path):
        _write_merged(tmp_path, "AABA-201910", last_close=70.0)
        p = UnifiedMarketDataProvider(merged_dir=str(tmp_path))
        assert p.get_price_data("AABA") is not None        # finds the -YYYYMM file

    def test_most_recent_suffix_wins(self, tmp_path):
        _write_merged(tmp_path, "DUP-200001", last_close=1.0)
        _write_merged(tmp_path, "DUP-202010", last_close=9.0)
        p = UnifiedMarketDataProvider(merged_dir=str(tmp_path))
        assert p.get_price_data("DUP")["Close"].iloc[-1] == pytest.approx(9.0)

    def test_share_class_dash_dot(self, tmp_path):
        _write_merged(tmp_path, "BRK.B", last_close=600.0)
        p = UnifiedMarketDataProvider(merged_dir=str(tmp_path))
        assert p.get_price_data("BRK-B") is not None        # dash request, dot file

    def test_filter_universe_drops_quarantined(self, tmp_path):
        _write_merged(tmp_path, "GOOD", last_close=100.0)
        bad = _write_merged(tmp_path, "BAD", last_close=100.0)
        bad = bad.copy()
        bad["data_quality_status"] = "insufficient_history"
        bad.to_parquet(os.path.join(tmp_path, "BAD.parquet"))
        p = UnifiedMarketDataProvider(merged_dir=str(tmp_path))
        kept, dropped = p.filter_universe(["GOOD", "BAD"])
        assert kept == ["GOOD"] and "BAD" in dropped


# -------------------------------------------------------------------- merge ---
class TestCollisionNaming:
    def _fake_norgate(self, monkeypatch, tmp_path, sym):
        nor = tmp_path / "norgate"
        mer = tmp_path / "merged"
        nor.mkdir(); mer.mkdir()
        idx = pd.date_range("2020-01-01", periods=5, freq="D")
        pd.DataFrame({"Open": 1.0, "High": 1.0, "Low": 1.0, "Close": 1.0,
                      "Volume": 10.0}, index=idx).to_parquet(nor / f"{sym}.parquet")
        monkeypatch.setattr(paths, "NORGATE_ROOT", str(nor))
        monkeypatch.setattr(paths, "MERGED", str(mer))
        return mer

    def test_collision_writes_suffixed(self, monkeypatch, tmp_path):
        mer = self._fake_norgate(monkeypatch, tmp_path, "RECYC")
        merge.merge_delisted("RECYC", "CS", live_keys={"RECYC"})
        files = [f.name for f in mer.iterdir()]
        assert any(f.startswith("RECYC-") for f in files)     # suffixed
        assert "RECYC.parquet" not in files                   # bare ticker left free

    def test_no_collision_writes_bare(self, monkeypatch, tmp_path):
        mer = self._fake_norgate(monkeypatch, tmp_path, "SOLO")
        merge.merge_delisted("SOLO", "CS", live_keys=set())
        assert "SOLO.parquet" in [f.name for f in mer.iterdir()]


# -------------------------------------------------------------------- audit ---
class TestIndexValidation:
    def _setup(self, monkeypatch, tmp_path, vix_close=21.0, vix_src="polygon",
               vix_type="index"):
        mer = tmp_path / "merged"; aud = tmp_path / "audit"
        mer.mkdir(); aud.mkdir()
        monkeypatch.setattr(paths, "MERGED", str(mer))
        monkeypatch.setattr(paths, "AUDIT", str(aud))
        sane = {"SPX": 7000, "NDX": 28000, "RUT": 2800, "DJI": 50000,
                "OEX": 3600, "VXN": 30, "TNX": 45}
        for s, c in sane.items():
            _write_merged(str(mer), s, c, source="polygon", sec_type="index")
        _write_merged(str(mer), "VIX", vix_close, source=vix_src, sec_type=vix_type)
        return mer

    def test_all_good_zero_bad(self, monkeypatch, tmp_path):
        self._setup(monkeypatch, tmp_path)
        _, bad = audit.index_validation()
        assert bad == 0

    def test_vix_out_of_bounds_flags(self, monkeypatch, tmp_path):
        self._setup(monkeypatch, tmp_path, vix_close=151.0)   # delisted-equity value
        _, bad = audit.index_validation()
        assert bad >= 1

    def test_vix_wrong_source_flags(self, monkeypatch, tmp_path):
        self._setup(monkeypatch, tmp_path, vix_src="norgate")  # tail not from patch
        _, bad = audit.index_validation()
        assert bad >= 1

    def test_vix_wrong_type_flags(self, monkeypatch, tmp_path):
        self._setup(monkeypatch, tmp_path, vix_type="equity_or_etf")
        _, bad = audit.index_validation()
        assert bad >= 1


# ------------------------------------------------------------- enforcement ---
class TestPitEnforcement:
    def test_trim_to_membership(self):
        from helpers.pit_enforcement import trim_to_membership
        idx = pd.date_range("2004-01-01", "2026-01-01", freq="D")
        df = pd.DataFrame({"Close": 1.0}, index=idx)
        span = (pd.Timestamp("2020-01-01"), pd.Timestamp("2022-01-01"))
        out = trim_to_membership(df, span, warmup_days=100)
        assert out.index.min() >= pd.Timestamp("2019-09-23")   # ~100d before join
        assert out.index.max() <= pd.Timestamp("2022-01-01")   # not after leave

    def test_trim_noop_without_span(self):
        from helpers.pit_enforcement import trim_to_membership
        df = pd.DataFrame({"Close": [1.0, 2.0]},
                          index=pd.date_range("2020-01-01", periods=2))
        assert len(trim_to_membership(df, None)) == 2


# ------------------------------------------------------------------ aliases ---
class TestAliasMap:
    @pytest.mark.parametrize("old,new", [
        ("UTX", "RTX"), ("ANTM", "ELV"), ("KORS", "CPRI"), ("YHOO", "AABA"),
        ("BLL", "BALL"), ("PCLN", "BKNG"), ("FB", "META"),
    ])
    def test_known_renames(self, old, new):
        from helpers.point_in_time import normalise_pit_ticker
        assert normalise_pit_ticker(old) == new


# -------------------------------------------- daily gating: warm-up + gaps ---
class TestMemberMask:
    def test_warmup_and_gap_bars_excluded(self):
        from helpers.pit_enforcement import build_member_mask, mask_signal
        idx = pd.date_range("2010-01-01", "2010-12-31", freq="D")
        intervals = [(pd.Timestamp("2010-03-01"), pd.Timestamp("2010-05-31")),
                     (pd.Timestamp("2010-09-01"), pd.Timestamp("2010-10-31"))]
        mask = build_member_mask(idx, intervals)
        assert not mask.loc["2010-01-15"]   # warm-up (before first join)
        assert mask.loc["2010-04-15"]       # inside spell 1
        assert not mask.loc["2010-07-15"]   # GAP between spells
        assert mask.loc["2010-09-15"]       # inside spell 2
        assert not mask.loc["2010-12-15"]   # after last leave

        sig = pd.Series(1, index=idx)       # strategy wants to be long every day
        out = mask_signal(sig, mask)
        assert out.loc["2010-01-15"] == -1  # warm-up forced flat -> not traded
        assert out.loc["2010-04-15"] == 1   # tradeable inside a spell
        assert out.loc["2010-07-15"] == -1  # gap forced flat -> not traded

    def test_mask_signal_noop_without_mask(self):
        from helpers.pit_enforcement import mask_signal
        sig = pd.Series([1, 0, -1])
        assert list(mask_signal(sig, None)) == [1, 0, -1]

    def test_empty_intervals_all_false(self):
        from helpers.pit_enforcement import build_member_mask
        idx = pd.date_range("2010-01-01", periods=5, freq="D")
        assert not build_member_mask(idx, []).any()

    def test_missing_post_leave_bar_marks_last_member_close(self):
        from helpers.pit_enforcement import build_forced_exit_mask
        idx = pd.bdate_range("2020-01-01", "2020-01-07")
        forced = build_forced_exit_mask(
            idx,
            [(pd.Timestamp("2020-01-01"), pd.Timestamp("2020-01-07"))],
            backtest_end="2020-12-31",
            exit_buffer_days=10,
        )
        assert forced.sum() == 1
        assert forced.loc["2020-01-07"]


class TestMembershipIntervals:
    def test_nq_gap_splits_into_two_spells(self, tmp_path):
        import json
        from helpers.pit_enforcement import _nq100_intervals
        dates = (list(pd.date_range("2020-01-01", "2020-02-28", freq="D"))
                 + list(pd.date_range("2020-06-01", "2020-07-31", freq="D")))
        df = pd.DataFrame({"date": [d.strftime("%Y-%m-%d") for d in dates],
                           "tickers_json": [json.dumps(["AAA"])] * len(dates)})
        path = tmp_path / "nq.parquet"
        df.to_parquet(path)
        iv = _nq100_intervals("2020-01-01", "2020-12-31", str(path))
        assert len(iv["AAA"]) == 2          # the 3-month gap creates a 2nd spell

    def test_nq_continuous_is_one_spell(self, tmp_path):
        import json
        from helpers.pit_enforcement import _nq100_intervals
        dates = pd.date_range("2020-01-01", "2020-06-30", freq="D")
        df = pd.DataFrame({"date": [d.strftime("%Y-%m-%d") for d in dates],
                           "tickers_json": [json.dumps(["BBB"])] * len(dates)})
        path = tmp_path / "nq.parquet"
        df.to_parquet(path)
        iv = _nq100_intervals("2020-01-01", "2020-12-31", str(path))
        assert len(iv["BBB"]) == 1


# ----------------------------------------- date-aware recycled resolution ---
class TestDateAwareResolution:
    def _recycled(self, tmp_path):
        # historical Sun-era JAVA (delisted, suffixed) + a live namesake JAVA
        _write_merged(tmp_path, "JAVA-201001", 5.0, start="2005-01-01", n=20)
        _write_merged(tmp_path, "JAVA", 99.0, start="2022-01-01", n=20)
        return UnifiedMarketDataProvider(merged_dir=str(tmp_path))

    def test_historical_window_picks_suffixed(self, tmp_path):
        p = self._recycled(tmp_path)
        path = p._resolve("JAVA", "2005-01-05", "2005-01-15")
        assert os.path.basename(path) == "JAVA-201001.parquet"

    def test_current_window_picks_bare(self, tmp_path):
        p = self._recycled(tmp_path)
        path = p._resolve("JAVA", "2022-01-05", "2022-01-15")
        assert os.path.basename(path) == "JAVA.parquet"

    def test_no_dates_legacy_prefers_bare(self, tmp_path):
        p = self._recycled(tmp_path)
        assert os.path.basename(p._resolve("JAVA")) == "JAVA.parquet"

    def test_get_price_data_serves_correct_era(self, tmp_path):
        p = self._recycled(tmp_path)
        hist = p.get_price_data("JAVA", "2005-01-05", "2005-01-15")
        assert hist["Close"].iloc[-1] == pytest.approx(5.0)   # Sun-era, not 99

    def test_interval_loader_combines_old_and_new_eras(self, tmp_path):
        _write_merged(tmp_path, "SNDK-201605", 5.0, start="2016-04-01", n=20)
        _write_merged(tmp_path, "SNDK", 90.0, start="2025-02-01", n=20)
        p = UnifiedMarketDataProvider(merged_dir=str(tmp_path))
        intervals = [
            (pd.Timestamp("2016-04-05"), pd.Timestamp("2016-04-15")),
            (pd.Timestamp("2025-02-05"), pd.Timestamp("2025-02-15")),
        ]
        out = p.get_price_data_for_intervals(
            "SNDK", intervals, warmup_days=0, exit_buffer_days=0)
        assert set(out["Close"].unique()) == {5.0, 90.0}
        assert out.index.min() == pd.Timestamp("2016-04-05")
        assert out.index.max() == pd.Timestamp("2025-02-15")

    def test_interval_screen_keeps_good_spell_and_drops_incomplete_spell(self, tmp_path):
        _write_merged(tmp_path, "DUAL-201605", 5.0, start="2016-04-01", n=30)
        _write_merged(tmp_path, "DUAL", 90.0, start="2025-03-01", n=10)
        p = UnifiedMarketDataProvider(merged_dir=str(tmp_path))
        spells = [
            (pd.Timestamp("2016-04-05"), pd.Timestamp("2016-04-20")),
            (pd.Timestamp("2025-02-01"), pd.Timestamp("2025-03-05")),
        ]
        kept, audit = p.filter_membership_intervals(
            "DUAL", spells, tolerance_days=2)
        assert kept == [spells[0]]
        assert [row["action"] for row in audit] == ["keep", "drop"]
        assert "starts_after_join" in audit[1]["reason"]

    def test_interval_screen_drops_quarantined_spell(self, tmp_path):
        _write_merged(
            tmp_path, "BAD", 5.0, start="2020-01-01", n=30,
            status="flagged")
        p = UnifiedMarketDataProvider(merged_dir=str(tmp_path))
        spells = [(pd.Timestamp("2020-01-05"), pd.Timestamp("2020-01-20"))]
        kept, audit = p.filter_membership_intervals("BAD", spells)
        assert kept == []
        assert audit[0]["reason"] == "status=flagged"


class TestFilterUniverseFlagged:
    def test_flagged_excluded_by_default(self, tmp_path):
        _write_merged(tmp_path, "GOOD", 100.0)
        fl = _write_merged(tmp_path, "FL", 100.0).copy()
        fl["data_quality_status"] = "flagged"
        fl.to_parquet(os.path.join(tmp_path, "FL.parquet"))
        p = UnifiedMarketDataProvider(merged_dir=str(tmp_path))
        kept, dropped = p.filter_universe(["GOOD", "FL"])
        assert kept == ["GOOD"] and "FL" in dropped

    def test_flagged_kept_when_opted_in(self, tmp_path):
        fl = _write_merged(tmp_path, "FL", 100.0).copy()
        fl["data_quality_status"] = "flagged"
        fl.to_parquet(os.path.join(tmp_path, "FL.parquet"))
        p = UnifiedMarketDataProvider(merged_dir=str(tmp_path))
        kept, _ = p.filter_universe(["FL"], exclude_statuses=("insufficient_history",))
        assert kept == ["FL"]


class TestFilterUniverseAsOf:
    """#361 — the liquidity/history screens must be strictly causal.

    Without `as_of` the screen reads the LAST `lookback` bars of the file, so a
    historical universe is screened on today's tape. Measured on a 673-name
    seasoned sample anchored 2010-01-01 at a $1M/day floor: 44 names (15.2% of
    the true universe) were dropped despite being liquid at the anchor — every
    one a delisting or bankruptcy — and 96 illiquid ones were kept.
    """

    @staticmethod
    def _ramp(d, name, closes, volumes, start="2009-01-01"):
        """A series whose liquidity CHANGES over time — the whole point. The
        constant-close `_write_merged` fixture cannot express this, and a
        constant series cannot fail for the reason these tests claim."""
        n = len(closes)
        idx = pd.date_range(start, periods=n, freq="D")
        pd.DataFrame({
            "open": closes, "high": closes, "low": closes, "close": closes,
            "volume": volumes, "vwap": float("nan"), "source": "polygon",
            "security_type": "CS", "adjustment_factor": 1.0,
            "adjustment_method": "none", "data_quality_status": "ok",
        }, index=idx).to_parquet(os.path.join(d, name + ".parquet"))
        return idx

    def _dying(self, d):
        """Liquid through 2009, a husk by the end — the RTHYL/ENDPQ shape.
        $10 x 1M shares = $10M/day, decaying to $10 x 100 = $1k/day."""
        return self._ramp(d, "DYING", [10.0] * 400, [1e6] * 200 + [100.0] * 200)

    def _reborn(self, d):
        """The mirror: illiquid early, liquid late. Kept by the tail screen
        purely on information that did not exist at the anchor."""
        return self._ramp(d, "REBORN", [10.0] * 400, [100.0] * 200 + [1e6] * 200)

    def test_liquid_at_the_anchor_is_kept_when_as_of_is_given(self, tmp_path):
        idx = self._dying(str(tmp_path))
        p = UnifiedMarketDataProvider(merged_dir=str(tmp_path))
        kept, dropped = p.filter_universe(
            ["DYING"], min_avg_dollar_volume=1e6, as_of=idx[199])
        assert kept == ["DYING"], dropped

    def test_same_name_is_dropped_by_the_tail_screen(self, tmp_path):
        """The bug itself, pinned: identical call, no as_of, opposite answer."""
        self._dying(str(tmp_path))
        p = UnifiedMarketDataProvider(merged_dir=str(tmp_path))
        kept, dropped = p.filter_universe(["DYING"], min_avg_dollar_volume=1e6)
        assert kept == [] and "DYING" in dropped

    def test_illiquid_at_the_anchor_is_dropped_when_as_of_is_given(self, tmp_path):
        idx = self._reborn(str(tmp_path))
        p = UnifiedMarketDataProvider(merged_dir=str(tmp_path))
        kept, dropped = p.filter_universe(
            ["REBORN"], min_avg_dollar_volume=1e6, as_of=idx[199])
        assert kept == [] and "REBORN" in dropped

    def test_same_name_is_kept_by_the_tail_screen(self, tmp_path):
        """The look-ahead half of the same bug."""
        self._reborn(str(tmp_path))
        p = UnifiedMarketDataProvider(merged_dir=str(tmp_path))
        kept, _ = p.filter_universe(["REBORN"], min_avg_dollar_volume=1e6)
        assert kept == ["REBORN"]

    def test_min_bars_counts_only_bars_up_to_as_of(self, tmp_path):
        idx = self._ramp(str(tmp_path), "SHORT", [5.0] * 300, [1e6] * 300)
        p = UnifiedMarketDataProvider(merged_dir=str(tmp_path))
        kept, dropped = p.filter_universe(["SHORT"], min_bars=100, as_of=idx[49])
        assert kept == [] and "bars=50<100" in dropped["SHORT"]
        assert p.filter_universe(["SHORT"], min_bars=100)[0] == ["SHORT"]

    def test_no_bars_on_or_before_as_of_is_dropped(self, tmp_path):
        self._ramp(str(tmp_path), "LATE", [5.0] * 30, [1e6] * 30,
                   start="2020-01-01")
        p = UnifiedMarketDataProvider(merged_dir=str(tmp_path))
        kept, dropped = p.filter_universe(
            ["LATE"], min_avg_dollar_volume=1.0, as_of="2010-01-01")
        assert kept == [] and "no bars on or before 2010-01-01" in dropped["LATE"]

    def test_tz_aware_as_of_is_accepted(self, tmp_path):
        """The store is tz-naive; a tz-aware anchor from a caller must not
        raise on comparison."""
        self._dying(str(tmp_path))
        p = UnifiedMarketDataProvider(merged_dir=str(tmp_path))
        kept, _ = p.filter_universe(
            ["DYING"], min_avg_dollar_volume=1e6,
            as_of=pd.Timestamp("2009-07-18", tz="UTC"))
        assert kept == ["DYING"]

    def test_exclude_statuses_is_not_sliced(self, tmp_path):
        """Deliberate, and pinned so it is not 'fixed' silently:
        data_quality_status is the merge pipeline's retrospective verdict on
        the FILE, not a point-in-time field. Reading it as-of would read a
        verdict that did not exist yet."""
        idx = self._ramp(str(tmp_path), "QUAR", [10.0] * 400, [1e6] * 400)
        df = pd.read_parquet(os.path.join(tmp_path, "QUAR.parquet"))
        df["data_quality_status"] = ["ok"] * 399 + ["flagged"]
        df.to_parquet(os.path.join(tmp_path, "QUAR.parquet"))
        p = UnifiedMarketDataProvider(merged_dir=str(tmp_path))
        kept, dropped = p.filter_universe(["QUAR"], as_of=idx[199])
        assert kept == [] and dropped["QUAR"] == "status=flagged"

    def test_warns_when_screening_numerically_without_as_of(self, tmp_path, caplog):
        self._dying(str(tmp_path))
        p = UnifiedMarketDataProvider(merged_dir=str(tmp_path))
        with caplog.at_level("WARNING",
                             logger="src.data.unified_market_data_provider"):
            p.filter_universe(["DYING"], min_avg_dollar_volume=1e6)
        assert any("as_of" in r.message for r in caplog.records), caplog.records

    def test_no_warning_when_as_of_is_supplied(self, tmp_path, caplog):
        idx = self._dying(str(tmp_path))
        p = UnifiedMarketDataProvider(merged_dir=str(tmp_path))
        with caplog.at_level("WARNING",
                             logger="src.data.unified_market_data_provider"):
            p.filter_universe(["DYING"], min_avg_dollar_volume=1e6, as_of=idx[199])
        assert [r.message for r in caplog.records] == []

    def test_no_warning_for_a_status_only_screen(self, tmp_path, caplog):
        """Status screening is legitimately not point-in-time, so warning there
        would train the reader to ignore the warning."""
        self._dying(str(tmp_path))
        p = UnifiedMarketDataProvider(merged_dir=str(tmp_path))
        with caplog.at_level("WARNING",
                             logger="src.data.unified_market_data_provider"):
            p.filter_universe(["DYING"])
        assert [r.message for r in caplog.records] == []


class TestMergedProviderWiring:
    def test_service_factory_exposes_merged_provider(self):
        from services import get_data_service
        with patch.dict("config.CONFIG", {"data_provider": "merged"}):
            fetcher = get_data_service()
        assert fetcher.__module__ == "src.data.unified_market_data_provider"

    def test_merged_indices_use_bare_names(self):
        from helpers.ticker_normalizer import normalize_ticker
        assert normalize_ticker("I:VIX", "merged") == "VIX"
        assert normalize_ticker("^GSPC", "merged") == "SPX"


class TestAtomicManifest:
    def test_write_atomic_no_temp_leftover(self, monkeypatch, tmp_path):
        from src.data.pipeline import manifest, paths
        mer = tmp_path / "merged"; meta = tmp_path / "metadata"
        mer.mkdir(); meta.mkdir()
        _write_merged(str(mer), "AAA", 10.0)
        monkeypatch.setattr(paths, "MERGED", str(mer))
        monkeypatch.setattr(paths, "METADATA", str(meta))
        monkeypatch.setattr(paths, "ensure_dirs", lambda: None)
        cls = pd.DataFrame({"symbol": ["AAA"], "bucket": ["common_to_both"],
                            "polygon_ticker": ["AAA"]})
        summary = pd.DataFrame({"status": ["ok"], "bucket": ["common_to_both"]})
        manifest.write_manifest(summary, index_rows=None, cls=cls)
        out = meta / "dataset_manifest.json"
        assert out.exists()
        data = json.loads(out.read_text())
        assert data["merged_files_total"] == 1
        assert not list(meta.glob("*.tmp*"))   # temp swapped away


class TestPitSimulationExecution:
    @staticmethod
    def _frame(index):
        df = pd.DataFrame(index=index)
        for col in ("Open", "High", "Low", "Close"):
            df[col] = 100.0
        df["Volume"] = 1_000_000.0
        df["ATR_14"] = 1.0
        df["ATR_14_pct"] = 0.01
        df["RSI_14"] = 50.0
        df["SMA200_dist_pct"] = 0.0
        df["Volume_Spike"] = 1.0
        return df

    @staticmethod
    def _config():
        return {
            "execution_time": "open",
            "slippage_pct": 0.0,
            "commission_per_share": 0.0,
            "max_pct_adv": 0.0,
            "volume_impact_coeff": 0.0,
            "htb_rate_annual": 0.0,
            "exclude_open_positions": False,
            "risk_free_rate": 0.0,
        }

    def test_first_nonmember_open_exits_and_cannot_reenter(self):
        from helpers.portfolio_simulations import run_portfolio_simulation
        idx = pd.bdate_range("2020-01-01", "2020-01-10")
        df = self._frame(idx)
        df["_pit_member"] = idx <= pd.Timestamp("2020-01-07")
        df["_pit_force_exit"] = False
        signals = pd.Series(1, index=idx)

        with patch.dict("config.CONFIG", self._config()):
            result = run_portfolio_simulation(
                {"AAA": df}, {"AAA": signals}, 10_000.0, 0.5,
                None, None, None, {"type": "none"})

        assert result["Trades"] == 1
        trade = result["trade_log"][0]
        assert trade["ExitDate"][:10] == "2020-01-08"
        assert trade["ExitReason"] == "PIT Membership Exit"

    def test_no_post_leave_bar_forces_last_close_exit(self):
        from helpers.portfolio_simulations import run_portfolio_simulation
        idx = pd.bdate_range("2020-01-01", "2020-01-07")
        df = self._frame(idx)
        df["_pit_member"] = True
        df["_pit_force_exit"] = False
        df.loc[idx[-1], "_pit_force_exit"] = True
        signals = pd.Series(1, index=idx)

        with patch.dict("config.CONFIG", self._config()):
            result = run_portfolio_simulation(
                {"AAA": df}, {"AAA": signals}, 10_000.0, 0.5,
                None, None, None, {"type": "none"})

        trade = result["trade_log"][0]
        assert trade["ExitDate"][:10] == "2020-01-07"
        assert trade["ExitReason"] == "PIT Membership Exit (last available close)"

    def test_short_is_covered_on_first_nonmember_open(self):
        from helpers.portfolio_simulations import run_portfolio_simulation
        idx = pd.bdate_range("2020-01-01", "2020-01-10")
        df = self._frame(idx)
        df["_pit_member"] = idx <= pd.Timestamp("2020-01-07")
        df["_pit_force_exit"] = False
        signals = pd.Series(0, index=idx)
        signals.iloc[0] = -2

        with patch.dict("config.CONFIG", self._config()):
            result = run_portfolio_simulation(
                {"AAA": df}, {"AAA": signals}, 10_000.0, 0.5,
                None, None, None, {"type": "none"})

        trade = result["trade_log"][0]
        assert trade["Trade"].startswith("Short")
        assert trade["ExitDate"][:10] == "2020-01-08"
        assert trade["ExitReason"] == "PIT Membership Exit"
