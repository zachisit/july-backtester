"""Output filenames built from strategy names must be Windows-legal.

Regression guard for the incident where a strategy named ``EMA_PB-A3_ADX>20``
produced output CSVs whose names contained ``>`` (illegal on Windows). Once
those files were committed, ``git checkout`` aborted on every Windows machine,
because Git fails the entire checkout when the OS rejects one path.

The fix routes the strategy-name-to-filename step (both sites in
``helpers/summary.py``) through the shared ``sanitize_symbol_for_filename``.
These tests pin that the composed helper leaves legal names unchanged and strips
every Windows-illegal character from the rest.
"""
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

    def test_legal_names_unchanged_from_prior_behaviour(self):
        # The historical cosmetic transforms (drop spaces/parens) are preserved,
        # so already-legal strategy filenames do not churn.
        assert _safe_strategy_name("SMA Crossover (20/50)") == "SMA_Crossover_20_50"
        assert _safe_strategy_name("MACD Crossover") == "MACD_Crossover"
