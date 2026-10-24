"""Re-verify every mutation claim published on the #381 epic.

Two things the original runs did not do:

  1. They ran with bytecode caching ON. A write/restore cycle can leave a stale
     .pyc, and a stale .pyc turns a KILLED mutant into a SURVIVING one -- which
     reads as "the guard is decorative", the exact conclusion this epic keeps
     drawing. PYTHONDONTWRITEBYTECODE=1 here.

  2. They did not assert the substitution APPLIED. Several used `sed` patterns
     against code that later changed; a pattern that no longer matches mutates
     nothing and the tests pass, which is indistinguishable from a surviving
     mutant. Every mutation below asserts exactly one match before running, and
     asserts the file is byte-restored afterwards.

Run:  python scripts/reverify_sizing_mutants.py
"""
import os
from pathlib import Path
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.environ.get("REVERIFY_PYTHON", sys.executable)
ENG = os.path.join(ROOT, "helpers", "portfolio_simulations.py")
SIZ = os.path.join(ROOT, "helpers", "position_sizing.py")
GM = "tests/test_engine_characterization.py"
CONS = "tests/test_position_sizing_consolidation.py"
SBAR = "tests/test_signal_bar_stop.py"
LADDER = "tests/test_stop_ladder_symmetry.py"
DIAG = "tests/test_sizing_diagnostics.py"
DIAG_ALL = "tests/test_sizing_diagnostics_all_paths.py"

# (label, file, old, new, test targets)
MUTANTS = [
    # ---- #384 ----------------------------------------------------------
    ("#384 unit-count gate removed", ENG,
     '                if sizing_method in ("risk_pct_capped", "fixed_contracts"):',
     '                if False:  # MUTANT', [GM, CONS]),
    ("#384 fixed_contracts + 1", SIZ,
     '    return float(config.get("fixed_contracts_per_trade", 1))',
     '    return float(config.get("fixed_contracts_per_trade", 1)) + 1  # MUTANT',
     [GM, CONS]),
    ("#384 heat side-output dropped", ENG,
     '                        sizing_kwargs["stop_distance_pct"] = _rp_stop_dist_pts / raw_entry_price',
     '                        pass  # MUTANT', [GM, CONS]),
    # ---- #385 ----------------------------------------------------------
    ("#385 cap applied to unmargined too", SIZ,
     "    if margined:", "    if True:  # MUTANT", [GM, CONS]),
    ("#385 cap never applied", SIZ,
     "    if margined:", "    if False:  # MUTANT", [GM, CONS]),
    ("#385 notional ceiling removed", SIZ,
     "        units = min(units, ceiling)", "        pass  # MUTANT", [GM, CONS]),
    # Match the actual ceiling calculation, rather than unrelated config reads.
    ("#385 ceiling reverted to allocation", SIZ,
     """    ceiling_pct = config.get("risk_pct_capped_max_notional_pct", 1.0)
    if (price is not None and price > 0 and point_value > 0""",
     """    ceiling_pct = config.get("allocation_per_trade", 0.10)  # MUTANT
    if (price is not None and price > 0 and point_value > 0""",
     [GM, CONS]),
    # ---- #386 ----------------------------------------------------------
    ("#386 equity short drops size_mults", ENG,
     "                    shares = shares * _s_size_mult\n\n                    # Unit-count methods",
     "                    shares = shares  # MUTANT\n\n                    # Unit-count methods", [GM, SBAR]),
    ("#386 futures short drops size_mults", ENG,
     "                    shares = shares * _s_size_mult\n\n                    # Unit-vs-dollar conversion",
     "                    shares = shares  # MUTANT\n\n                    # Unit-vs-dollar conversion", [CONS]),
    ("#386 futures short back to a two-method list", ENG,
     "                    _s_sizing_method = _s_eq_sizing_method",
     '                    _s_sizing_method = _s_eq_sizing_method if _s_eq_sizing_method in ("risk_pct_capped","fixed_contracts") else "___"  # MUTANT',
     [GM, SBAR]),
    # ---- ladder guard --------------------------------------------------
    ("ladder: points branch hardcodes buffer", ENG,
     """                                _sb_bar.get('High'), _sb_bar.get('Low'),
                                stop_config.get("buffer", 0.0), "long")""",
     """                                _sb_bar.get('High'), _sb_bar.get('Low'),
                                0.0, "long")  # MUTANT""", [LADDER]),
    ("ladder: points branch stops walking", ENG,
     """                        _sb_sz = _walk_back(prev_trading_dates[symbol],
                                            signal_date,
                                            stop_config.get("bars_back", 0))""",
     "                        _sb_sz = signal_date  # MUTANT", [LADDER, SBAR]),
    # ---- #387 ----------------------------------------------------------
    ("#387 report skipped on zero-trade path", ENG,
     "        _sizing_diag.log_report()\n        return None",
     "        return None  # MUTANT", [DIAG]),
    ("#387 ceiling diagnostic removed", SIZ,
     '            _record_sizing_diagnostic(kwargs, "clamped_by_notional_ceiling")',
     '            pass  # MUTANT', [DIAG]),
]


def run(targets):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    p = subprocess.run(
        [PY, "-m", "pytest", *targets, "-q", "--no-header", "-p", "no:warnings"],
        cwd=ROOT, capture_output=True, text=True, env=env)
    if p.returncode not in (0, 1):
        raise RuntimeError("pytest did not complete: " + p.stdout[-2000:] + p.stderr[-1000:])
    tail = [l for l in p.stdout.splitlines()
            if l.startswith("FAILED") or " passed" in l or " failed" in l]
    return (tail[-1] if tail else "?", sum(
        1 for l in p.stdout.splitlines() if l.startswith("FAILED")), p.returncode)


def main():
    print("control:")
    for t in (GM, CONS, SBAR, LADDER, DIAG, DIAG_ALL):
        line, nf, returncode = run([t])
        print("   %-46s %s" % (t, line))
        if returncode != 0 or nf:
            print("!! control failed; no mutation results can be trusted")
            return 1
    print()

    bad = []
    for label, path, old, new, targets in MUTANTS:
        source_path = Path(path)
        original_bytes = source_path.read_bytes()
        src = original_bytes.decode("utf-8").replace("\r\n", "\n")
        n = src.count(old)
        if n != 1:
            print("!! %-46s SUBSTITUTION MATCHED %d TIMES -- not a result" % (label, n))
            bad.append(label)
            continue
        try:
            source_path.write_text(src.replace(old, new, 1), encoding="utf-8", newline="\n")
            line, nf, returncode = run(targets)
        finally:
            source_path.write_bytes(original_bytes)
        assert source_path.read_bytes() == original_bytes, "restore failed for " + path
        killed = returncode == 1 and nf > 0
        verdict = "KILLED (%d)" % nf if killed else "SURVIVED/INVALID"
        print("%-10s %-46s %s" % (verdict, label, line))
        if not killed:
            bad.append(label)

    print()
    print("survived or unapplied:", bad if bad else "none")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
