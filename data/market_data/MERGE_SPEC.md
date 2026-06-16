# MERGE_SPEC.md — Unified Norgate + Polygon Market Data Pipeline

**Status:** APPROVED — *price-adjustment decision signed off 2026-06-05: **Option A (total-return forward-adjustment)**. Build proceeding.*

**One-line:** Norgate = historical truth, Polygon = daily update, `merged/` = the only thing the backtester reads, audit = trust proof.

---

## 0. Scope & guardrails

- Sources are **Norgate per-symbol parquet** and **Polygon** only. No other local data is touched except the explicitly-approved `required_strategy_asset` fallback (§7 Case F), and only after it passes the same audits.
- **Never overwrite Norgate raw.** Norgate parquet files are read-only inputs. All adjustment is applied as a *factor stored separately*, never by mutating Norgate.
- **Never blindly append Polygon.** Every Polygon row passes normalization → adjustment → audit before it can land in `merged/`.
- **Fail closed.** Any unresolved adjustment, identity, or completeness problem sends the symbol/day to `audit/` and is excluded from the approved dataset — it does not silently merge.

---

## 1. Proven facts from source inspection (not assumptions)

Established by `scripts/inspect_norgate_schema.py` and `scripts/probe_adjustment_basis.py` (read-only):

| Fact | Evidence |
|---|---|
| Norgate parquet schema = `Open, High, Low, Close, Volume` (float32), index `Datetime` (tz-naive, midnight) | All 6 sampled symbols identical; **no** dividend/split/factor/unadjusted columns exist |
| Norgate history range | 1990-01-02 → **2026-04-22** (global last bar = the cutoff) |
| Norgate is **split-adjusted** | AAPL 7:1 (2014-06-09) and 4:1 (2020-08-31) splits show **no** price cliff; the one 0.48× day (2000-09-29) is the real AAPL profit-warning crash, correctly preserved |
| Norgate is **also dividend back-adjusted (total-return)** | KO 2017-06 close $34.59 vs Polygon $45.79 → ratio **0.759**, rising monotonically to **1.0000** exactly at 2026-04-22. XLF same shape (0.846→1.0000). Polygon `adjusted=true`==`adjusted=false` over the gap (no splits) → the entire gap is **dividends**. Magnitudes match each name's dividend yield. |
| **Polygon `adjusted=true` = split-adjusted only** (dividends NOT removed) | Direct comparison above |
| The seam is **level-continuous** | At 2026-04-22 the Norgate/Polygon ratio = **1.0000** (total-return back-adjustment pins the most-recent bar to the actual market price). Splicing Polygon right after Norgate's last bar produces **no day-1 price cliff.** |

**Conclusion:** Norgate and Polygon use **different price conventions** — Norgate = total-return (split + dividend) back-adjusted; Polygon = split-adjusted price-return. They agree at the anchor and diverge backward in history by accumulated dividends.

---

## 3. ✅ DECISION (signed off 2026-06-05: Option A) — canonical forward convention

The merged series **must be one convention end-to-end.** A strategy computing a 200-day indicator on, say, 2026-07-01 looks back across the 04-22 seam; if history is total-return and the patch is price-return, the indicator mixes two different quantities for ~200 days. More fundamentally: **every existing backtest and every validated strategy was computed on Norgate total-return prices.** Forward-testing on a different quantity than you backtested invalidates the comparison.

Three options:

### Option A — Total-return forward-adjustment, anchored at 2026-04-22  ✅ RECOMMENDED
Extend Norgate's existing total-return convention forward. Mechanics:
- Pull the Polygon patch as **`adjusted=false` (raw)** so stored bars never retroactively change.
- Maintain a per-symbol cumulative `adjustment_factor`, starting at **1.0 at the 04-22 anchor** (= actual price = Norgate's last bar).
- On each **split** (ratio *s*) ex-date *D* in the patch: multiply `adjustment_factor` for all dates ≥ *D* by *s* (removes the split discontinuity).
- On each **cash dividend** *d* (prev close *C*) ex-date *D*: multiply `adjustment_factor` for all dates ≥ *D* by `(1 + d/C)` (reinvests the dividend → total-return).
- Canonical merged price = `raw × adjustment_factor`. Raw is always recoverable as `merged_price / adjustment_factor`.
- Splits + dividends come from `/v3/reference/splits` and `/v3/reference/dividends`, themselves audited (`corporate_action_warnings.csv`).
- **Pros:** merged series is the *same quantity* the strategies were validated on; seamless; Norgate raw untouched; deterministic & reproducible. **Cons:** must ingest & audit Polygon corporate actions (bounded — only ~6 weeks of events so far).

### Option B — Split-adjusted-only forward (accept a convention seam)  ⚠️ quick but flawed
Splice Polygon split-adjusted price directly; do not dividend-adjust forward.
- **Pros:** simplest; no dividend ingestion. **Cons:** introduces small artificial ex-dividend price drops in the patch (~yield/4 per quarter per name) that the historical convention never had; mixes two conventions inside every lookback window straddling the seam for ~200 days; forward data is a *different quantity* than the backtest. Acceptable only as a short-term, explicitly-documented approximation.

### Option C — Convert Norgate history to split-only (un-adjust dividends)  ❌ rejected
Would require reversing 36 years of dividend back-adjustment with no stored dividend factors — a full retroactive reconstruction across 36k symbols, and it would violate "don't touch Norgate." Impractical.

> **Splits must be handled in the patch window under *all* options** (a split is a hard discontinuity, never optional). Only *dividend* handling differs between A and B.

**Recommendation: Option A.** It is the only choice that keeps "Norgate = truth, seamless merge" literally true and keeps forward data consistent with every existing backtest.

**→ DECISION: Option A selected (2026-06-05).** The build implements total-return forward-adjustment anchored at 2026-04-22 per the mechanics above. Full policy in `metadata/price_adjustment_policy.md`.

---

## 4. Folder layout (subsystem root: `data/market_data/`)

```
data/market_data/
├── MERGE_SPEC.md                  # this file
├── norgate_raw/                   # symlink/pointer to read-only Norgate repo (never written)
├── polygon_raw/                   # immutable API responses: YYYY-MM-DD.json (grouped daily)
├── polygon_normalized/            # YYYY-MM-DD.parquet (canonical schema, raw prices)
├── polygon_patch/                 # {ticker}.parquet — per-ticker patch, 2026-04-23 →
├── merged/                        # {ticker}.parquet — THE backtester source
├── audit/                         # all audit CSVs + final_approval_report.md
├── logs/                          # per-run logs
└── metadata/                      # classification tables, price_adjustment_policy.md, factors
```
Code (created only after sign-off): `scripts/update_market_data.py`, `scripts/build_merged_dataset.py`, `scripts/audit_merged_dataset.py`, `src/data/unified_market_data_provider.py`.

---

## 5. Core authority rule & the seam

- Norgate authoritative for **date ≤ 2026-04-22**.
- Polygon authoritative for **date > 2026-04-22**.
- Polygon overlap pulled from **~2026-04-08** but used **only for calibration/audit (§6)** — overlap rows are **never** stored in `merged/`.
- Backtester reads **`data/market_data/merged/` only.**

---

## 6. Universe classification (Task 1)

Tag every symbol into exactly one bucket:

| Bucket | Rule |
|---|---|
| `common_to_both` | Norgate-active AND matched to a Polygon ticker (after §7 normalization) |
| `norgate_only_delisted_keep` | Norgate last bar < 2026-04-22 AND security is common stock / ETF → **keep full history, never patch** (survivorship-bias-free requirement) |
| `norgate_only_review` | Norgate-active but no Polygon match → **review first** (likely notation mapping issue, not truly missing) |
| `norgate_only_exclude_nontradeable` | Norgate-only breadth (`#`), internal indices (`$`) not used by a strategy, and junk → kept in a list, excluded from universe |
| `polygon_only_new_listing` | Polygon-active AND not in Norgate AND **first Polygon daily bar > 2026-04-22** |
| `polygon_only_coverage_gap` | Polygon-active AND not in Norgate AND first bar **≤** 2026-04-22 (existed before cutoff → not a new listing) |
| `polygon_only_exclude_nontradeable` | Polygon warrants/rights/units/preferreds/SP/ADR-warrant/etc. not required by a strategy |
| `required_strategy_asset` | Explicit allow-list used by strategies: GLD, SLV, TLT, IEF, HYG, LQD, UUP, SPX, NDX, RUT, VIX, VXN, TNX (+ any discovered in `custom_strategies/`) |

**Outputs:** `metadata/symbol_classification.csv` + one CSV per bucket (`norgate_delisted_kept.csv`, `norgate_only_review.csv`, `norgate_only_excluded_nontradeable.csv`, `polygon_only_new_listings.csv`, `polygon_only_coverage_gaps.csv`, `polygon_only_excluded_nontradeable.csv`, `required_strategy_assets.csv`).

---

## 7. Ticker mapping & identity checks (Task 2)

Normalization handles: `BRK.B`↔`BRK-B`, `BF.B`↔`BF-B`, class shares, preferred `-X`↔`pX`, warrant `_W`/trailing-`W`↔`.WS`, Norgate↔Polygon notation. **Never merge by raw ticker string alone.**

Before accepting a Norgate→Polygon splice, all must hold:
- ticker matches after normalization,
- security type matches,
- **price continuity in the overlap window** (no unexplained cliff at the seam),
- no ticker-reuse signature (a delisted ticker later reissued to a different company).

Uncertain identity → `audit/identity_review.csv`, **not patched.** Mapping anomalies → `audit/ticker_mapping_issues.csv`.

---

## 8–10. Pull / normalize / adjust (Tasks 3–5)

**Pull (Task 3):** Polygon grouped-daily `/v2/aggs/grouped/.../{date}`, **`adjusted=false`**, stored verbatim as `polygon_raw/YYYY-MM-DD.json`. Daily run re-pulls a **trailing 5 trading-day window** to catch Polygon revisions. Idempotent: re-running a date overwrites that date's rows, never duplicates.

**Normalize (Task 4):** canonical schema —
`date, ticker, open, high, low, close, volume, vwap, source, security_type, adjustment_factor, adjustment_method, data_quality_status`.
Timestamps → tz-naive NY market dates (midnight), matching Norgate. No duplicate (ticker, date). Output `polygon_normalized/YYYY-MM-DD.parquet` and per-ticker `polygon_patch/{ticker}.parquet`.

**Adjust (Task 5 — Option A):** apply the cumulative total-return `adjustment_factor` from the 04-22 anchor (mechanics in §3). `adjustment_method ∈ {none, split, dividend, split+dividend}`. Any symbol whose corporate actions can't be safely resolved → `audit/adjustment_continuity_report.csv` + `audit/corporate_action_warnings.csv`, excluded from approval. Final policy written to `metadata/price_adjustment_policy.md` once §3 is signed off.

---

## 11. Overlap calibration (Task 6)

For every `common_to_both` symbol, compare Norgate vs Polygon over **2026-04-08…04-22**: same-date O/H/L/C/V, splice ratio, price-cliff detection, adjustment-mismatch detection, identity mismatch, stale/bad bars. Expected result given §1: ratio ≈ **1.0000** at the anchor. Anything materially off 1.0 is a red flag → audit. Overlap rows are **calibration only, never stored.** Outputs: `audit/overlap_calibration.csv`, `audit/splice_ratio_report.csv`, `audit/join_gap_warnings.csv`.

---

## 12. Merge logic (Task 7)

| Case | Action |
|---|---|
| A `common_to_both` | Norgate ≤ 04-22 + Polygon (adjusted) > 04-22 → `merged/{ticker}.parquet` |
| B `norgate_only_delisted_keep` | Full Norgate history, no patch; series end is valid, **not** missing data |
| C `norgate_only_review` | Keep, **do not patch**, write review report until identity resolved |
| D `polygon_only_new_listing` | Polygon-only from first valid bar; tag `history_start`; block long-lookback strategies until enough bars |
| E `polygon_only_coverage_gap` | Excluded from default universe; logged in coverage-gap report |
| F `required_strategy_asset` | Patch if in both; else approved local parquet **only after** passing the same OHLC + continuity audits — never blind |

---

## 13. Audit checks & gates (Task 8, 11)

**Per-row:** `high ≥ max(open,close)`, `low ≤ min(open,close)`, all prices > 0, volume ≥ 0, no duplicate (ticker,date), no null date/ticker.
**Time-series:** missing expected trading days, phantom trading days, stale/flat-line, extreme one-day return spikes, zero-volume anomalies, **seam cliff check at 04-22→04-23**, corporate-action validation, delisting-during-patch = clean end, new-listing insufficient-history flags.
**Completeness gate:** if a Polygon day returns materially fewer symbols than expected → **store the raw pull but mark the update FAILED**; do not approve/merge that day.

**Fail-closed triggers (Task 11):** unsolved adjustment mismatch · uncertain identity · too-few-symbols day · suspicious gap without a corporate action · duplicate rows · invalid OHLC · new listing with insufficient lookback · local parquet fails audit.

**Outputs:** `audit/patch_audit.csv`, `missing_bars.csv`, `bad_ohlc_rows.csv`, `duplicate_rows.csv`, `completeness_gate.csv`, `delisting_during_patch.csv`, `insufficient_history_new_listings.csv`, `final_approval_report.md`.

---

## 14. Unified loader (Task 9)

`src/data/unified_market_data_provider.py` — `UnifiedMarketDataProvider` exposing only:
- `load_prices(symbols, start_date, end_date)`
- `load_universe(date, universe_name)`
- `load_required_asset(symbol, start_date, end_date)`

Reads **`merged/` only.** Backtester is agnostic to row origin, but every merged row keeps `source`, `adjustment_factor`, `adjustment_method`, `data_quality_status` internally for audit.

---

## 15. Daily updater (Task 10)

`python scripts/update_market_data.py --asof latest`:
1. find latest completed trading day → 2. re-pull trailing 5 trading days (raw JSON) → 3. normalize → 4. update patch files → 5. rebuild affected merged tickers → 6. run all audits → 7. **approve or fail** → 8. write logs + `final_approval_report.md`. Idempotent and safe to rerun.

---

## 16. Final report fields (Task 12)

`audit/final_approval_report.md` must state: # common to both · # Norgate delisted eq/ETF kept · # Norgate-only excluded/reviewed · # Polygon-only new listings added · # Polygon-only coverage gaps excluded · # patched dates · # failed symbols · **APPROVED / NOT APPROVED for backtesting & forward testing.**

---

## 17. Open review gates (consolidated)

1. **§3 price-adjustment convention — A vs B.** ✅ RESOLVED 2026-06-05: Option A.
2. Subsystem root `data/market_data/` — confirm (default assumed).
3. `required_strategy_asset` allow-list — confirm the symbol set before Case F local fallback is used.
4. "Materially fewer symbols" completeness threshold — propose **< 95%** of trailing-median symbol count fails the day (to confirm at build time).
