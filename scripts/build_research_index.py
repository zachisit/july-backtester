"""
Build a consolidated research index CSV from all backtest run summaries.

Outputs: output/research_index.csv

Merges:
  - All output/runs/*/overall_portfolio_summary.csv files
  - LLM verdict data (beats_spy, smooth_verdict, longest_flat_months) from
    output/runs/*/llm_verdict.json when available
  - code_file and param_count parsed from each @register_strategy block found
    anywhere under custom_strategies/ — the bundled plugins plus any private
    submodule mounted underneath. Strategies with no matching source file just
    leave those two columns blank.

Run from the project root:

    rtk python scripts/build_research_index.py
    rtk python scripts/build_research_index.py --runs-only myrun other-run
"""

import csv
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PROJECT_ROOT = Path(__file__).parent.parent
RUNS_DIR = PROJECT_ROOT / "output" / "runs"
STRATEGY_DIR = PROJECT_ROOT / "custom_strategies"
OUTPUT_PATH = PROJECT_ROOT / "output" / "research_index.csv"

# ---------------------------------------------------------------------------
# Step 1: Build strategy → code file + param count lookup
# ---------------------------------------------------------------------------

def _extract_strategies_from_file(py_path: Path) -> dict[str, dict]:
    """
    Parse a strategy Python file and return:
      {strategy_name: {"code_file": rel_path, "param_count": N}}
    """
    rel_path = str(py_path.relative_to(PROJECT_ROOT))
    source = py_path.read_text(encoding="utf-8")
    results = {}

    # Find each @register_strategy(...) block — find name= and params= within it
    # Pattern: @register_strategy followed by a parenthesised block
    # We look for name="..." and count top-level keys in params={...}
    block_pattern = re.compile(
        r'@register_strategy\s*\((.*?)\)\s*\ndef\s+\w+',
        re.DOTALL
    )
    for m in block_pattern.finditer(source):
        block = m.group(1)

        # Extract name
        name_m = re.search(r'name\s*=\s*"([^"]+)"', block)
        if not name_m:
            continue
        name = name_m.group(1)

        # Count params keys (robust: count occurrences of quoted-string: value at
        # the top level of the params dict — handles multi-line dicts)
        param_count = 0
        params_m = re.search(r'params\s*=\s*\{(.*?)\}', block, re.DOTALL)
        if params_m:
            params_body = params_m.group(1)
            # Count key entries: lines with "key": pattern
            param_count = len(re.findall(r'"[^"]+"\s*:', params_body))

        results[name] = {"code_file": rel_path, "param_count": param_count}

    return results


def build_strategy_lookup() -> dict[str, dict]:
    lookup = {}
    # Recursive: picks up the plugins bundled in custom_strategies/ as well as
    # any private submodule mounted underneath it.
    for py_path in sorted(STRATEGY_DIR.rglob("*.py")):
        if py_path.name == "_TEMPLATE_strategy.py" or py_path.name.startswith("__"):
            continue
        try:
            extracted = _extract_strategies_from_file(py_path)
            lookup.update(extracted)
        except Exception as e:
            print(f"  [WARN] Could not parse {py_path.name}: {e}", file=sys.stderr)
    return lookup


# ---------------------------------------------------------------------------
# Step 2: Load all LLM verdicts
# ---------------------------------------------------------------------------

def load_llm_verdicts() -> dict[tuple, dict]:
    """
    Returns a dict keyed by (run_id, strategy_name, portfolio) with verdict fields.
    Falls back to (run_id, strategy_name) if portfolio not matched.
    """
    verdicts: dict[tuple, dict] = {}
    for verdict_path in sorted(RUNS_DIR.rglob("llm_verdict.json")):
        try:
            with open(verdict_path, encoding="utf-8") as fh:
                data = json.load(fh)
            run_id = data.get("run_id", verdict_path.parent.name)
            for s in data.get("strategies", []):
                strat = s.get("strategy", "")
                portfolio = s.get("portfolio", "")
                smoothness = s.get("curve_smoothness") or {}
                entry = {
                    "llm_beats_spy": s.get("beats_spy"),
                    "llm_smooth_verdict": smoothness.get("smooth_verdict"),
                    "llm_longest_flat_months": smoothness.get("longest_flat_streak_months"),
                    "llm_smoothness_r2": smoothness.get("smoothness_r2"),
                }
                verdicts[(run_id, strat, portfolio)] = entry
                verdicts[(run_id, strat)] = entry  # fallback key
        except Exception as e:
            print(f"  [WARN] Could not parse {verdict_path}: {e}", file=sys.stderr)
    return verdicts


# ---------------------------------------------------------------------------
# Step 3: Consolidate all CSVs
# ---------------------------------------------------------------------------

# Canonical output columns (in order)
OUTPUT_COLS = [
    "run_id", "data_provider", "start_date", "end_date", "timeframe",
    "Portfolio", "Strategy",
    "P&L (%)", "vs. SPY (B&H)",
    "Max DD", "Max Rcvry (d)", "Avg Rcvry (d)",
    "Calmar", "Sharpe",
    "Roll.Sharpe(avg)", "Roll.Sharpe(min)", "Roll.Sharpe(last)",
    "Profit Factor", "Win Rate",
    "Avg. Hold (d)", "Trades",
    "Expectancy (R)", "SQN",
    "OOS P&L (%)", "WFA Verdict", "Rolling WFA",
    "MC Verdict", "MC Score",
    # Enrichment columns
    "llm_beats_spy", "llm_smooth_verdict", "llm_longest_flat_months",
    "llm_smoothness_r2",
    "code_file", "param_count",
]


def _normalise_row(row: dict, header: list[str]) -> dict:
    """Map raw CSV row (any header variant) to OUTPUT_COLS."""
    out = {c: "" for c in OUTPUT_COLS}
    # Direct copy for matching names
    for col in header:
        if col in out:
            out[col] = row.get(col, "")
    # Aliases for benchmark columns that vary by run
    for alias in ["vs. SPY (B&H)", "vs. SPY(B&H)"]:
        if alias in row and not out["vs. SPY (B&H)"]:
            out["vs. SPY (B&H)"] = row[alias]
    # run_id is always present
    if not out["run_id"] and "run_id" in row:
        out["run_id"] = row["run_id"]
    return out


def collect_csv_rows(prefix_filter: list[str] | None = None) -> list[dict]:
    all_rows = []
    csv_files = sorted(RUNS_DIR.rglob("overall_portfolio_summary.csv"))

    for csv_path in csv_files:
        run_id = csv_path.parent.name
        if prefix_filter and not any(run_id.startswith(p) for p in prefix_filter):
            continue
        try:
            with open(csv_path, newline="", encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                header = reader.fieldnames or []
                for row in reader:
                    norm = _normalise_row(row, header)
                    # The summary CSV normally carries run_id as its first
                    # column, but the directory name is equally authoritative
                    # and is what load_llm_verdicts() falls back to. Without
                    # this, a CSV missing the column would silently lose every
                    # enrichment field on the join below.
                    if not norm["run_id"]:
                        norm["run_id"] = run_id
                    all_rows.append(norm)
        except Exception as e:
            print(f"  [WARN] Could not read {csv_path}: {e}", file=sys.stderr)

    return all_rows


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    prefix_filter = None
    if len(sys.argv) > 1 and sys.argv[1] == "--runs-only":
        if len(sys.argv) < 3:
            print("error: --runs-only requires at least one run-id prefix", file=sys.stderr)
            sys.exit(1)
        prefix_filter = sys.argv[2:]
        print(f"Filtering to run prefixes: {prefix_filter}")

    print("Building strategy lookup...", end=" ", flush=True)
    lookup = build_strategy_lookup()
    print(f"{len(lookup)} strategies found.")

    print("Loading LLM verdicts...", end=" ", flush=True)
    verdicts = load_llm_verdicts()
    print(f"{len(verdicts)} verdict keys loaded.")

    print("Collecting CSV rows...", end=" ", flush=True)
    rows = collect_csv_rows(prefix_filter)
    print(f"{len(rows)} rows from {len(list(RUNS_DIR.rglob('overall_portfolio_summary.csv')))} CSVs.")

    # Enrich each row
    for row in rows:
        run_id = row["run_id"]
        strat = row["Strategy"]
        portfolio = row["Portfolio"]

        # LLM verdict lookup: try full key first, then fallback
        verdict = verdicts.get((run_id, strat, portfolio)) or verdicts.get((run_id, strat)) or {}
        for k in ("llm_beats_spy", "llm_smooth_verdict", "llm_longest_flat_months", "llm_smoothness_r2"):
            row[k] = verdict.get(k, "")

        # Code file + param count
        code_info = lookup.get(strat) or {}
        row["code_file"] = code_info.get("code_file", "")
        row["param_count"] = code_info.get("param_count", "")

    # Write output
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=OUTPUT_COLS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nWrote {len(rows)} rows → {OUTPUT_PATH}")
    print(f"Columns: {', '.join(OUTPUT_COLS)}")

    # Quick stats
    wfa_pass = sum(1 for r in rows if r.get("WFA Verdict") == "Pass")
    with_verdict = sum(1 for r in rows if r.get("llm_smooth_verdict"))
    print(f"\nQuick stats:")
    print(f"  WFA Pass rows:       {wfa_pass} / {len(rows)}")
    print(f"  Rows with LLM data:  {with_verdict}")


if __name__ == "__main__":
    main()
