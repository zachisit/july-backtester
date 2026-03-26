"""
Tests for trade_analyzer/report_generator.py — pure helper functions only.

Targets three functions with no existing tests:
  - add_line_to_summary:       format + append logic for all flag combinations
  - generate_wfa_summary:      all guard/early-return branches + verdict labels
  - extract_key_metrics_for_console:  section parsing, regex extraction, exception safety
"""
import math
import pytest
import numpy as np
import pandas as pd

from trade_analyzer.report_generator import (
    add_line_to_summary,
    generate_wfa_summary,
    extract_key_metrics_for_console,
)


# ---------------------------------------------------------------------------
# add_line_to_summary
# ---------------------------------------------------------------------------

class TestAddLineToSummary:

    def test_none_value_appends_na(self):
        lines = []
        add_line_to_summary(lines, "Label", None)
        assert len(lines) == 1
        assert "N/A" in lines[0]

    def test_nan_value_appends_na(self):
        lines = []
        add_line_to_summary(lines, "Label", float("nan"))
        assert "N/A" in lines[0]

    def test_pd_na_appends_na(self):
        lines = []
        add_line_to_summary(lines, "Label", pd.NA)
        assert "N/A" in lines[0]

    def test_pos_inf_appends_inf_string(self):
        lines = []
        add_line_to_summary(lines, "Label", float("inf"))
        assert "inf" in lines[0]

    def test_neg_inf_appends_neg_inf_string(self):
        lines = []
        add_line_to_summary(lines, "Label", float("-inf"))
        assert "-inf" in lines[0]

    def test_currency_format_two_decimal_places(self):
        lines = []
        add_line_to_summary(lines, "Total", 1500.5, is_curr=True)
        assert "$1,500.50" in lines[0]

    def test_currency_negative_value(self):
        lines = []
        add_line_to_summary(lines, "Loss", -300.0, is_curr=True)
        assert "$-300.00" in lines[0]

    def test_pct_flag_treats_input_as_fractional(self):
        """is_pct=True: 0.65 → '65.00%'"""
        lines = []
        add_line_to_summary(lines, "Win Rate", 0.65, is_pct=True)
        assert "65.00%" in lines[0]

    def test_raw_pct_val_treats_input_as_already_scaled(self):
        """is_raw_pct_val=True: 65.0 → '65.00%'"""
        lines = []
        add_line_to_summary(lines, "Win Rate", 65.0, is_raw_pct_val=True)
        assert "65.00%" in lines[0]

    def test_fmt_spec_applied(self):
        lines = []
        add_line_to_summary(lines, "Trades", 42.7, fmt_spec="{:.0f}")
        assert "43" in lines[0]

    def test_default_string_conversion(self):
        lines = []
        add_line_to_summary(lines, "Status", "Profitable")
        assert "Profitable" in lines[0]

    def test_integer_value_default(self):
        lines = []
        add_line_to_summary(lines, "Count", 10)
        assert "10" in lines[0]

    def test_label_is_left_aligned_at_start_of_line(self):
        lines = []
        add_line_to_summary(lines, "MyLabel", 99.0)
        assert lines[0].startswith("MyLabel")

    def test_multiple_calls_append_separately(self):
        lines = []
        add_line_to_summary(lines, "A", 1.0)
        add_line_to_summary(lines, "B", 2.0)
        assert len(lines) == 2


# ---------------------------------------------------------------------------
# generate_wfa_summary
# ---------------------------------------------------------------------------

class TestGenerateWfaSummary:

    def test_returns_tuple_of_two_strings(self):
        title, text = generate_wfa_summary({}, None, None)
        assert isinstance(title, str)
        assert isinstance(text, str)

    def test_title_is_wfa_heading(self):
        title, _ = generate_wfa_summary({}, None, None)
        assert "Walk-Forward" in title

    def test_disabled_when_split_ratio_none(self):
        _, text = generate_wfa_summary({}, None, None)
        assert "disabled" in text.lower()

    def test_disabled_when_split_ratio_zero(self):
        _, text = generate_wfa_summary({}, None, 0)
        assert "disabled" in text.lower()

    def test_could_not_compute_when_no_split_date_but_ratio_set(self):
        """wfa_result empty + ratio=0.8 but split_date=None → insufficient data."""
        _, text = generate_wfa_summary({}, None, 0.8)
        assert "could not" in text.lower() or "insufficient" in text.lower()

    def test_pass_verdict_shows_consistent_message(self):
        result = {"oos_pnl_pct": 0.05, "wfa_verdict": "Pass"}
        _, text = generate_wfa_summary(result, "2022-01-01", 0.8)
        assert "Pass" in text
        assert "consistent" in text.lower()

    def test_overfitted_verdict_shows_caution(self):
        result = {"oos_pnl_pct": -0.10, "wfa_verdict": "Likely Overfitted"}
        _, text = generate_wfa_summary(result, "2022-01-01", 0.8)
        assert "Likely Overfitted" in text
        assert "CAUTION" in text

    def test_na_verdict_shows_insufficient_message(self):
        result = {"oos_pnl_pct": None, "wfa_verdict": "N/A"}
        _, text = generate_wfa_summary(result, "2022-01-01", 0.8)
        assert "N/A" in text
        assert "Insufficient" in text

    def test_split_ratio_appears_as_percentage(self):
        result = {"oos_pnl_pct": 0.03, "wfa_verdict": "Pass"}
        _, text = generate_wfa_summary(result, "2022-01-01", 0.8)
        assert "80%" in text
        assert "20%" in text

    def test_split_date_appears_in_output(self):
        result = {"oos_pnl_pct": 0.03, "wfa_verdict": "Pass"}
        _, text = generate_wfa_summary(result, "2022-06-15", 0.7)
        assert "2022-06-15" in text

    def test_oos_pnl_none_shows_na_line(self):
        """oos_pnl_pct=None → N/A shown for that specific line."""
        result = {"oos_pnl_pct": None, "wfa_verdict": "Pass"}
        _, text = generate_wfa_summary(result, "2022-01-01", 0.8)
        assert "N/A" in text

    def test_oos_pnl_shown_as_percentage_when_present(self):
        result = {"oos_pnl_pct": 0.0512, "wfa_verdict": "Pass"}
        _, text = generate_wfa_summary(result, "2022-01-01", 0.8)
        # +5.12% formatted with +.2%
        assert "+5.12%" in text


# ---------------------------------------------------------------------------
# extract_key_metrics_for_console
# ---------------------------------------------------------------------------

class TestExtractKeyMetricsForConsole:

    def test_empty_list_returns_empty_dict(self):
        assert extract_key_metrics_for_console([]) == {}

    def test_none_input_returns_empty_dict(self):
        """Exception path: None is not iterable → caught → returns {}."""
        assert extract_key_metrics_for_console(None) == {}

    def test_irrelevant_section_titles_ignored(self):
        sections = [{"title": "Some Other Section", "data": "key: value"}]
        result = extract_key_metrics_for_console(sections)
        assert result == {}

    def test_overall_metrics_section_parsed(self):
        sections = [{"title": "Overall Performance Metrics", "data": "Total Profit: 1000"}]
        result = extract_key_metrics_for_console(sections)
        assert "Total Profit" in result

    def test_numeric_value_converted_to_float(self):
        sections = [{"title": "Overall Performance Metrics", "data": "Win Rate: 55.5%"}]
        result = extract_key_metrics_for_console(sections)
        assert result.get("Win Rate") == pytest.approx(55.5)

    def test_currency_value_stripped_of_dollar_and_comma(self):
        sections = [{"title": "Overall Performance Metrics", "data": "Total Profit: $1,234.56"}]
        result = extract_key_metrics_for_console(sections)
        assert result.get("Total Profit") == pytest.approx(1234.56)

    def test_non_numeric_value_stored_as_string(self):
        sections = [{"title": "Overall Performance Metrics", "data": "Status: Active"}]
        result = extract_key_metrics_for_console(sections)
        assert result.get("Status") == "Active"

    def test_cagr_extracted_by_regex(self):
        sections = [{"title": "Overall Performance Metrics", "data": "CAGR: 12.34%"}]
        result = extract_key_metrics_for_console(sections)
        # Regex extraction specifically looks for 'CAGR:' pattern
        assert "CAGR" in result
        assert result["CAGR"] == pytest.approx(12.34)

    def test_mc_percentile_section_extracts_average_cagr(self):
        data = "CAGR Average: 8.5%\nFinal Equity Average: 120000"
        sections = [{"title": "Monte Carlo: Percentile Analysis", "data": data}]
        result = extract_key_metrics_for_console(sections)
        assert "MC Average CAGR" in result

    def test_multiple_sections_merged_into_one_dict(self):
        sections = [
            {"title": "Overall Performance Metrics", "data": "Win Rate: 60%"},
            {"title": "Monte Carlo: Percentile Analysis", "data": "CAGR Average: 10.0%"},
        ]
        result = extract_key_metrics_for_console(sections)
        assert "Win Rate" in result
        assert "MC Average CAGR" in result

    def test_section_with_no_colon_lines_ignored(self):
        sections = [{"title": "Overall Performance Metrics", "data": "no colon here\njust text"}]
        # No colon → no entries parsed from line split; still returns dict
        result = extract_key_metrics_for_console(sections)
        assert isinstance(result, dict)
