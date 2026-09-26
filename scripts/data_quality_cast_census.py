"""scripts/data_quality_cast_census.py

Census for issue #389: how much of the corpus sits at *exactly* the data-quality
gate only because CHECK 5 / CHECK 6 truncate their demerit charge to a whole
point?

helpers/data_quality.py charges two of its checks through int():

    CHECK 5   demerits += min(10, int(pct))        # zero-volume bars
    CHECK 6   demerits += min(20, int(pct / 2))    # missing bars

Every other demerit in the module is an integer already, so the truncation is
the only thing standing between a series and a fractional score. A series
charged int(39.98 / 2) == 19 instead of 19.99 scores exactly 80.0 and clears a
"score < threshold" gate by 0.0 points. This script measures how many series
that is, and how many of them the untruncated charge would demote.

WHAT IT COMPARES
----------------
Two copies of the *same* file: helpers/data_quality.py as committed, and the
same source with those two casts removed and **nothing else changed**. The
variant is built at run time by substituting the two expressions in the source
text, each substitution asserted to match exactly once, and exec'ing the result.
It is not a hand-maintained fork, so it cannot drift from the original, and if
either line is edited the script fails loudly instead of silently censusing a
stale copy.

EVERY COUNT IS CAP-SCOPED
-------------------------
CHECK 6's charge is clamped, and a clamped term is inert to changes inside it.
At the committed cap of 20 every series missing >= 40% of its bars is pinned at
20 demerits, so removing the cast cannot move it; raise the cap and the same
series becomes sensitive. The headline count therefore depends on the cap the
run was scored under, and a number measured on one branch does not transfer to
another. --cap exists so the census can be stated against a proposed cap (e.g.
issue #382's 30) rather than re-quoted across branches. It rewrites the cap in
*both* copies, so the comparison stays cap-consistent.

DATA ACCESS
-----------
This reads data/market_data/merged/*.parquet directly rather than through
data_gate.py. That is deliberate and is not a licence to do the same elsewhere:
this is a QA audit *of* validate_ohlcv over the population that function exists
to score, so it must see the frames that function sees -- including the ones
the gate would reject. Do not copy this access pattern into anything that
fetches prices for a backtest.

For the same reason the frames are passed through untouched: no `source`
filtering, no de-duplication, no sorting. validate_ohlcv does not do those
things either, and the census measures the function as written.

OUTPUT
------
--json-out writes {"cap", "threshold", "corpus", "rows"}, where each row is a
*keyed* dict: symbol, bars, score_int, score_float -- or symbol plus `error`
for a frame that would not load. There is no per-row error field on a scored
row and no positional row format; the earlier hand-run artifact quoted on #389
used positional rows whose fourth field is zero_volume_pct (null when zero),
which reads convincingly as an error column and silently drops 2,798 of 35,309
series if joined as one. Join on `symbol`.

Floats are rounded to 6 dp on the way into the JSON only. Nothing upstream of
summarise() is rounded: it classifies on `score_float < threshold` and on
`score_int != score_float`, so a rounded value could move a series across the
gate or hide a mover.

USAGE
-----
    python scripts/data_quality_cast_census.py                       # cap as committed
    python scripts/data_quality_cast_census.py --cap 30              # against a proposed cap
    python scripts/data_quality_cast_census.py --workers 8 --json-out census.json

Census contributed by @shardul (issue #389).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import multiprocessing as mp
import os
import re
import sys
import time
import warnings
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CORPUS = PROJECT_ROOT / "data" / "market_data" / "merged"
DEFAULT_MODULE = PROJECT_ROOT / "helpers" / "data_quality.py"

# The two truncations under test. {cap} is filled in so a --cap run rewrites
# and then un-casts the same expression.
CAST_CHECK5 = ("demerits += min(10, int(pct))",
               "demerits += min(10, pct)")
CAST_CHECK6 = ("demerits += min({cap}, int(pct / 2))",
               "demerits += min({cap}, pct / 2)")

# CHECK 6's cap is *read out of the module under test*, not hardcoded here.
# A literal would be a second copy of a value another branch exists to change
# -- issue #382 raises it 20 -> 30 -- and on a tree where that has landed the
# literal no longer matches anything, so every substitution misses and the
# script refuses to run at all. It fails in the right direction, but it fails:
# the census would be unrunnable on the branch it most needs to be stated
# against. Detecting the cap keeps it runnable, and keeps --cap N meaning "score
# against N" rather than "score against N only if 20 is still committed".
# Derived from CAST_CHECK6[0] so the pattern and the substitution target are
# one spelling and cannot drift apart.
_CHECK6_CAP_RE = re.compile(
    re.escape(CAST_CHECK6[0]).replace(re.escape("{cap}"), r"(\d+)"))

# Bar-count strata. A one-year series missing 40% of its bars and a five-year
# series missing 40% of its bars are not the same finding, and the multi-year
# stratum is the one that carries a survivorship claim.
STRATA = (("all", 0), (">= 252 bars", 252), (">= 1260 bars", 1260))


# --------------------------------------------------------------------------
# Variant construction
# --------------------------------------------------------------------------

def _sub_once(src: str, old: str, new: str, what: str) -> str:
    """Replace `old` with `new`, asserting it appears exactly once.

    A census whose variant was built from a near-miss substitution is worse
    than no census, so a count other than 1 is fatal rather than a warning.
    """
    n = src.count(old)
    if n != 1:
        raise SystemExit(
            "[census] cannot build the un-cast variant: expected exactly one\n"
            "         occurrence of {} in the module under test, found {}.\n"
            "         Looked for: {!r}\n"
            "         data_quality.py has changed; update the substitution\n"
            "         table in this script before trusting any count."
            .format(what, n, old))
    return src.replace(old, new)


def committed_check6_cap(src: str) -> int:
    """The CHECK 6 cap in force in the module under test."""
    found = _CHECK6_CAP_RE.findall(src)
    if len(found) != 1:
        raise SystemExit(
            "[census] cannot locate the CHECK 6 charge: expected exactly one\n"
            "         `demerits += min(<cap>, int(pct / 2))`, found {}.\n"
            "         data_quality.py has changed; update the substitution\n"
            "         table in this script before trusting any count."
            .format(len(found)))
    return int(found[0])


def build_variant_sources(module_path: Path,
                          cap: int | None) -> tuple[str, str, int]:
    """Return (as_committed_src, un_cast_src, effective_cap).

    Both sources are the same file. If `cap` is given, the CHECK 6 clamp is
    rewritten in both, so the pair differs only by the two casts at whatever
    cap is in force. The third element is the cap the pair was actually built
    at -- returned rather than re-derived by the caller so there is exactly one
    answer to "which cap was this run scored under".
    """
    src = module_path.read_text(encoding="utf-8")

    eff_cap = committed_check6_cap(src)
    if cap is not None and cap != eff_cap:
        src = _sub_once(src, CAST_CHECK6[0].format(cap=eff_cap),
                        CAST_CHECK6[0].format(cap=cap), "the CHECK 6 charge")
        eff_cap = cap

    un_cast = _sub_once(src, CAST_CHECK5[0], CAST_CHECK5[1], "the CHECK 5 cast")
    un_cast = _sub_once(un_cast,
                        CAST_CHECK6[0].format(cap=eff_cap),
                        CAST_CHECK6[1].format(cap=eff_cap),
                        "the CHECK 6 cast")
    return src, un_cast, eff_cap


def _exec_module(src: str, module_path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, str(module_path))
    mod = importlib.util.module_from_spec(spec)
    mod.__file__ = str(module_path)
    exec(compile(src, "{} [{}]".format(module_path, name), "exec"), mod.__dict__)
    return mod


# --------------------------------------------------------------------------
# Workers
# --------------------------------------------------------------------------

_MODS: dict = {}


def _init_worker(module_path: str, cap: int | None) -> None:
    # validate_ohlcv's pct_change raises a FutureWarning on current pandas, and
    # at corpus scale that is one warning per series on stderr -- enough output
    # to swamp a terminal or a captured log and, measured here, to kill the run.
    # Suppressed in the worker only: this census does not control that call and
    # is not the place to surface it.
    warnings.filterwarnings("ignore", category=FutureWarning)
    path = Path(module_path)
    as_committed, un_cast, _ = build_variant_sources(path, cap)
    _MODS["committed"] = _exec_module(as_committed, path, "as_committed")
    _MODS["uncast"] = _exec_module(un_cast, path, "un_cast")


def _score_one(file_path: str) -> dict:
    import pandas as pd

    symbol = Path(file_path).stem
    try:
        df = pd.read_parquet(file_path)
    except Exception as exc:  # a corrupt file is a finding, not a crash
        return {"symbol": symbol, "error": "{}: {}".format(type(exc).__name__, exc)}

    try:
        score_int, _ = _MODS["committed"].validate_ohlcv(df, symbol)
        score_flt, _ = _MODS["uncast"].validate_ohlcv(df, symbol)
    except Exception as exc:
        return {"symbol": symbol, "error": "{}: {}".format(type(exc).__name__, exc)}

    return {
        "symbol": symbol,
        "bars": int(len(df)),
        # Full precision. Rounding here would sit UPSTREAM of summarise(),
        # which classifies on `score_float < threshold` and on
        # `score_int != score_float` -- so a rounded row could move a series
        # across the gate or hide a mover. Measured on the 35,309-series
        # corpus it flips neither (nearest approach from below is 79.995885,
        # a 4.1e-03 margin against a 5e-07 granularity), but that margin is a
        # property of the data, not of this code. Round at the writer instead.
        "score_int": float(score_int),
        "score_float": float(score_flt),
    }


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------

def _round_row(row: dict) -> dict:
    """Trim float noise for the JSON artifact only -- never before summarise()."""
    return {k: (round(v, 6) if isinstance(v, float) else v) for k, v in row.items()}


def gate_delta(scored: list[dict], threshold: float) -> tuple[int, int, int, int]:
    """(committed_below, un_cast_below, from_the_at_gate_cohort, from_above).

    `len(low_quality)` in main.py is `sum(score < threshold)`, so this is the
    number the gate actually reports -- and it is NOT the size of the
    exactly-at-the-gate cohort. Removing a truncation can only raise a demerit
    charge, so score_float <= score_int for every series and no series crosses
    back; but a series that scored 80.4 committed can still fall under an 80.0
    gate un-cast, and it was never in the score_int == threshold cohort that
    every other line here counts. Splitting the delta keeps that residue
    visible instead of leaving it as an unexplained five.
    """
    committed = sum(1 for r in scored if r["score_int"] < threshold)
    un_cast = sum(1 for r in scored if r["score_float"] < threshold)
    crossers = [r for r in scored
                if r["score_int"] >= threshold > r["score_float"]]
    assert un_cast - committed == len(crossers), "score_float > score_int"
    at_gate = sum(1 for r in crossers if r["score_int"] == threshold)
    return committed, un_cast, at_gate, len(crossers) - at_gate


def summarise(rows: list[dict], threshold: float, cap: int) -> str:
    scored = [r for r in rows if "error" not in r]
    errors = [r for r in rows if "error" in r]
    n = max(len(scored), 1)

    out = []
    out.append("CHECK 6 cap in force : {}".format(cap))
    out.append("Gate threshold       : score < {}".format(threshold))
    out.append("Series scored        : {:,}{}".format(
        len(scored), "   ({} unreadable)".format(len(errors)) if errors else ""))
    out.append("")

    at_gate = [r for r in scored if r["score_int"] == threshold]
    demoted = [r for r in at_gate if r["score_float"] < threshold]
    stays = [r for r in at_gate if r["score_float"] >= threshold]

    out.append("At exactly {} as committed : {:,}   ({:.2f}% of corpus)".format(
        threshold, len(at_gate), len(at_gate) / n * 100))
    out.append("  demoted below the gate un-cast   : {:,}".format(len(demoted)))
    out.append("  still at {} un-cast          : {:,}   ({:.2f}% of corpus)".format(
        threshold, len(stays), len(stays) / n * 100))
    out.append("")

    out.append("{:>14}  {:>9}  {:>9}  {:>14}".format(
        "stratum", "at gate", "demoted", "still at gate"))
    for label, min_bars in STRATA:
        sub = [r for r in at_gate if r["bars"] >= min_bars]
        d = sum(1 for r in sub if r["score_float"] < threshold)
        out.append("{:>14}  {:>9,}  {:>9,}  {:>14,}".format(
            label, len(sub), d, len(sub) - d))
    out.append("")

    # How load-bearing the threshold constant becomes once the cast is gone.
    # A demoted series landing at 79.97 is excluded by a "< 80" gate and
    # re-included by a "< 79.5" one, so the residue moves with a constant that
    # nobody currently has to think about.
    if demoted:
        near = [r for r in demoted
                if threshold - 0.1 < r["score_float"] < threshold]
        lo = min(r["score_float"] for r in demoted)
        out.append("Demoted series land in [{:.4f}, {:.4f}); {:,} of {:,} land "
                   "within 0.1 of the gate.".format(
                       lo, threshold, len(near), len(demoted)))

    movers = [r for r in scored if r["score_int"] != r["score_float"]]
    out.append("Series whose score moves at all  : {:,}   ({:.2f}% of corpus)".format(
        len(movers), len(movers) / n * 100))
    out.append("")

    # What the gate in main.py actually reports, before and after. Swept
    # rather than quoted at one threshold because on this corpus the two
    # halves of #389 interfere: every demerit is integer-valued as committed,
    # so a sub-integer threshold move is a no-op until the cast is gone and
    # then works against it. One pair cannot show that; the column can.
    out.append("GATE DELTA  --  len(low_quality), i.e. sum(score < threshold)")
    out.append("{:>11}  {:>11}  {:>11}  {:>9}".format(
        "threshold", "committed", "un-cast", "delta"))
    for t in sorted({threshold - 1, threshold - 0.5, threshold,
                     threshold + 0.5, threshold + 1}):
        c, u, _, _ = gate_delta(scored, t)
        out.append("{:>11}  {:>11,}  {:>11,}  {:>+9,}{}".format(
            "{:g}".format(t), c, u, u - c,
            "   <- run threshold" if t == threshold else ""))
    _, _, _at, _above = gate_delta(scored, threshold)
    out.append("At {:g} the delta splits {:,} + {:,}: the first from the "
               "exactly-{:g} cohort".format(threshold, _at, _above, threshold))
    out.append("above, the second from series that cleared the gate as "
               "committed and are")
    out.append("counted nowhere else here.")

    if errors:
        out.append("")
        out.append("Unreadable:")
        for r in errors[:10]:
            out.append("  {}: {}".format(r["symbol"], r["error"]))
        if len(errors) > 10:
            out.append("  ... and {} more".format(len(errors) - 10))
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Census the int() truncation in data_quality CHECK 5/6 (#389).")
    ap.add_argument("--corpus", default=str(DEFAULT_CORPUS),
                    help="directory of *.parquet series (default: %(default)s)")
    ap.add_argument("--module", default=str(DEFAULT_MODULE),
                    help="path to the data_quality module under test")
    ap.add_argument("--cap", type=int, default=None,
                    help="override the CHECK 6 clamp in BOTH copies "
                         "(default: whatever the module under test commits to; "
                         "the effective value is printed and recorded in "
                         "--json-out)")
    ap.add_argument("--threshold", type=float, default=80.0,
                    help="the gate being cleared (default: %(default)s)")
    ap.add_argument("--workers", type=int,
                    default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--limit", type=int, default=None,
                    help="score only the first N series (smoke test)")
    ap.add_argument("--json-out", default=None,
                    help="write every scored row to this path as JSON")
    args = ap.parse_args(argv)

    module_path = Path(args.module)
    if not module_path.is_file():
        ap.error("module not found: {}".format(module_path))

    # Build once in the parent too: a substitution failure should abort before
    # a pool is spawned, not once per worker. The cap comes back from the same
    # call that built the pair, so what gets reported is what was scored.
    _, _, eff_cap = build_variant_sources(module_path, args.cap)

    corpus = Path(args.corpus)
    if not corpus.is_dir():
        ap.error("corpus directory not found: {}".format(corpus))
    files = sorted(str(p) for p in corpus.glob("*.parquet"))
    if args.limit:
        files = files[:args.limit]
    if not files:
        ap.error("no *.parquet files in {}".format(corpus))

    print("[census] {:,} series in {}".format(len(files), corpus), file=sys.stderr)
    print("[census] CHECK 6 cap {}, {} workers".format(eff_cap, args.workers),
          file=sys.stderr)

    t0 = time.time()
    rows: list[dict] = []
    with mp.Pool(args.workers, initializer=_init_worker,
                 initargs=(str(module_path), args.cap)) as pool:
        for i, row in enumerate(
                pool.imap_unordered(_score_one, files, chunksize=16), 1):
            rows.append(row)
            if i % 2000 == 0:
                el = time.time() - t0
                print("[census] {:,}/{:,}  {:.0f}s elapsed, ~{:.0f}s left".format(
                    i, len(files), el, el / i * (len(files) - i)), file=sys.stderr)

    print("[census] scored {:,} in {:.0f}s".format(len(rows), time.time() - t0),
          file=sys.stderr)

    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps({"cap": eff_cap, "threshold": args.threshold,
                        "corpus": str(corpus),
                        "rows": [_round_row(r) for r in rows]}, indent=1),
            encoding="utf-8")
        print("[census] wrote {}".format(args.json_out), file=sys.stderr)

    print()
    print(summarise(rows, args.threshold, eff_cap))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
