# Pattern scanner

Run `python scripts/pattern_scan.py --universe DASH,KHC --parquet-dir /path/to/prices` to produce a local HTML contact sheet. `--source yahoo` downloads daily bars. `--as-of YYYY-MM-DD` replays a historical window; Parquet bars are cut before the last 800 daily / 2,600 daily bars are selected. Yahoo replay requests a window ending at the selected date.

`--min-base` raises the base-length floor for both pattern families while retaining each family’s default minimum. Touch controls are `--min-touches` for triangles, `--min-touches-long` for rectangle/H&S ceilings, and `--floor-min-touches` for rectangle floors. `--tol-pct-floor` and `--tol-atr-mult` control clustering. Defaults preserve the original detector geometry.

The triangle applies an uptrend filter. Rectangle/H&S currently rank geometry and proximity; reconciliation of scoring and continuation conventions is tracked in #383. A report shows the data dates and counts of missing symbols, load failures, detector errors, qualified symbols, and displayed cards. A failed chart keeps its candidate card. `--json-out scan.json` exports parameters, counts, detected levels, and the winning tolerance source without embedding price frames.

The bundled `us_liquid.json` is the August 26, 2026 snapshot, described by its metadata sidecar. Refresh it with `python scripts/build_us_universe.py --min-adv 2e6`. The builder records refresh time and coverage, uses the last 20 sessions for dollar ADV, and preserves the existing file when no prices were scored.

Frozen CSV fixtures under `tests/fixtures/pattern_scan/` reconstruct the July 2 review tape (MDLZ 6,300 / SPY 8,413 / BIIB 8,754 full-history rows before tailing). Their manifest records source and fixture hashes, dates, default detections, levels, and scores. They pin MDLZ’s floor veto, XEL’s valid alternative floor, and unchanged DASH/KHC controls without network access.

The Pine companion draws boundary, confirm, target, and stop levels. Confirm alerts use the configured buffer. Its dash spacing respects TradingView’s line budget and forward-coordinate limit. Python tests do not compile Pine; the companion is reviewed against the Pine v5 documentation.
