# Price-Adjustment Policy — Unified Norgate + Polygon Dataset

**Decision date:** 2026-06-05 · **Convention: Option A — total-return forward-adjustment, anchored at 2026-04-22.**

## Established facts (proven, read-only inspection)

| Feed | Convention | How we know |
|---|---|---|
| **Norgate** (history ≤ 2026-04-22) | **Total-return** = split + dividend back-adjusted | KO 2017-06 = 0.759× Polygon, rising to **1.0000× at 2026-04-22**; XLF 0.846→1.0000. Polygon `adjusted=true`==`adjusted=false` over the gap (no splits) ⇒ entire gap is dividends. Ratios match each name's dividend yield. |
| **Polygon** `adjusted=true` (patch > 2026-04-22) | **Split-adjusted only** (dividends NOT removed) | Same comparison. |

The most-recent Norgate bar equals the actual market price (back-adjustment pins the anchor), so the 04-22→04-23 **seam is level-continuous** (ratio 1.0000) — no day-1 cliff.

## Canonical price definition

The canonical strategy price for **every** symbol and date is **total-return**, consistent with Norgate's existing convention and with every backtest already run on this engine. The merged series must be this one quantity end-to-end so that indicator lookback windows straddling the seam never mix conventions.

## Forward mechanics (patch > 2026-04-22)

1. Pull the Polygon patch as **`adjusted=false` (raw)** → stored immutably in `polygon_raw/`. Raw bars never change retroactively (only genuine corrections via the trailing-5-day re-pull).
2. Maintain a per-symbol cumulative `adjustment_factor`, **= 1.0 at the 2026-04-22 anchor** (anchor price = Norgate's last bar = actual market price).
3. For each **split** ratio *s* (e.g. 2:1 ⇒ *s*=2) with ex-date *D*: multiply `adjustment_factor` for all dates **≥ D** by *s*.
4. For each **cash dividend** *d* (prev close *C*) with ex-date *D*: multiply `adjustment_factor` for all dates **≥ D** by `(1 + d/C)`.
5. **Canonical merged price = `raw × adjustment_factor`.** Raw is always recoverable as `merged_price / adjustment_factor`.

Corporate actions come from Polygon `/v3/reference/splits` and `/v3/reference/dividends`, themselves audited (`audit/corporate_action_warnings.csv`). Norgate history is **never mutated**; it is already total-return and is consumed as-is with `adjustment_factor = 1.0`, `adjustment_method = norgate_native`.

## Provenance columns (every merged row)

| Column | Values |
|---|---|
| `source` | `norgate` / `polygon` / `local` |
| `adjustment_factor` | float; 1.0 for Norgate-native rows and the anchor |
| `adjustment_method` | `norgate_native` / `none` / `split` / `dividend` / `split+dividend` |
| `data_quality_status` | `ok` / `flagged` / `failed` |

## Fail-closed

If a symbol's forward corporate actions cannot be resolved (missing/ambiguous split or dividend, suspicious uncorroborated price gap), the symbol's patch is **not merged** — it is written to `audit/adjustment_continuity_report.csv` with `data_quality_status = failed` and excluded from the approved dataset.

## Rejected alternatives

- **Option B (split-adjusted-only forward):** introduces artificial ex-dividend drops the historical convention never had and makes forward data a different quantity than the backtest. Rejected.
- **Option C (un-adjust Norgate history to split-only):** requires reconstructing 36 years of dividend factors across 36k symbols with no stored data, and would mutate Norgate. Rejected.
