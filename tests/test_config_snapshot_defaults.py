"""#475 review nit 2: config_snapshot.json records the rule-universe defaults
a run fell back to, so changing a default (universe_min_price, #474) stays
traceable when an old run is re-run."""
import json

from helpers.rule_based_universe import DEFAULTS
from main import build_config_snapshot


def test_unset_key_records_resolved_default():
    snap = build_config_snapshot({"start_date": "2010-01-01"})
    rec = snap["_resolved_defaults"]["rule_based_universe"]
    assert rec["universe_min_price"] == DEFAULTS["universe_min_price"]
    assert set(rec) == set(DEFAULTS)
    assert snap["start_date"] == "2010-01-01"


def test_explicit_value_recorded_and_none_falls_back():
    snap = build_config_snapshot({"universe_min_price": 5.0, "universe_top_n": None})
    rec = snap["_resolved_defaults"]["rule_based_universe"]
    assert rec["universe_min_price"] == 5.0
    assert rec["universe_top_n"] == DEFAULTS["universe_top_n"]


def test_config_not_mutated_and_snapshot_serialises():
    cfg = {"universe_min_price": 1.0}
    snap = build_config_snapshot(cfg)
    assert "_resolved_defaults" not in cfg
    json.dumps(snap, default=str)
