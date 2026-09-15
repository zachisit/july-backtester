# Norgate → Parquet Export Guide

> **Norgate is frozen at 2026-04-22.** Everything below still works, but it only
> runs on a machine with a Norgate licence and the **Norgate Data Updater desktop
> app** (Windows/macOS) running locally — `norgatedata` talks to that app over a
> local socket, so it cannot run on a Linux server or in CI. Day-to-day the
> dataset is kept current by **Polygon**, not Norgate. See
> [Daily automation](#daily-automation) below before reaching for these commands.


## Full database dump (recommended)

To get a complete 1:1 copy of all Norgate data locally, run these three commands in order.
Use `--start-date 1990-01-01` — Norgate's earliest available data for most US equities.
Symbols with IPOs after 1990 automatically start from their first available date.

```bash
# Step 1 — All currently listed US equities (~13,930 symbols)
python scripts/norgate_to_parquet.py --database "US Equities" --output-dir parquet_data/data --start-date 1990-01-01

# Step 2 — All delisted / historical US equities (~20,873 symbols)
python scripts/norgate_to_parquet.py --database "US Equities Delisted" --output-dir parquet_data/data --start-date 1990-01-01 --skip-existing

# Step 3 — US and World indices (~1,615 symbols: VIX, SPX, TNX, sector indices, etc.)
python scripts/norgate_to_parquet.py --database "US Indices" --output-dir parquet_data/data --start-date 1990-01-01 --skip-existing
```

`--skip-existing` on Steps 2 and 3 skips any file already written — no duplicate work.

## Refreshing data

To update existing files with the latest bars, re-run without `--skip-existing`.
Omitting the flag overwrites every file with fresh data from Norgate.

```bash
python scripts/norgate_to_parquet.py --database "US Equities" --output-dir parquet_data/data --start-date 1990-01-01
```

## Other useful options

```bash
# Single watchlist (e.g. for a targeted refresh)
python scripts/norgate_to_parquet.py --watchlist "S&P 500" --output-dir parquet_data/data --start-date 1990-01-01

# Specific tickers only
python scripts/norgate_to_parquet.py --tickers AAPL MSFT NVDA --output-dir parquet_data/data --start-date 1990-01-01

# List all available databases
python -c "import norgatedata; print(norgatedata.databases())"

# List all available watchlists
python -c "import norgatedata; print(norgatedata.watchlists())"
```

## Validating the export

After running all three steps, verify that every Norgate symbol has a local Parquet file:

```bash
python scripts/validate_norgate_export.py
```

Reports per-database counts (Norgate vs local) and lists any missing symbols.
If anything is missing, fetch just those symbols:

```bash
python scripts/norgate_to_parquet.py --tickers AIMN DCBG --output-dir parquet_data/data --start-date 1990-01-01
```

Then re-run the validator to confirm `STATUS: ALL PRESENT`.

## Notes

- Output: one `.parquet` file per symbol in `parquet_data/data/` (e.g. `AAPL.parquet`, `$VIX.parquet`)
- Index symbols use Norgate's native `$` prefix (e.g. `$VIX`, `$SPX`) — no sanitization needed
- Each file has columns `Open, High, Low, Close, Volume` with a UTC DatetimeIndex
- Price adjustment: Total Return (split- and dividend-adjusted) — Norgate default
- To use the exported data: set `data_provider: "parquet"` in `config.py` (default dir is `parquet_data/data`)

---

## Daily automation

`.github/workflows/polygon-daily-update.yml` keeps `parquet_data/` current on a
schedule. Nobody needs to run anything by hand.

| Schedule (UTC) | What runs | Why |
|---|---|---|
| `0 10 * * *` (daily) | `scripts/polygon_daily_update.sh` | Appends new bars to files that already exist, commits the submodule, bumps its pointer on `main`. |
| `30 10 * * 6` (Saturday) | `scripts/polygon_new_listings.py`, then the daily pass | The daily updater only touches symbols that already have a file, so without this scan new IPOs never enter the universe. Weekly is deliberate — a new listing has no usable history for momentum/MR until it has 60–200 bars. |

10:00 UTC is 06:00 ET under EDT and 05:00 ET under EST. GitHub Actions cron has
no timezone support, so that hour of DST drift is unavoidable; both sides land
well after Polygon settles the prior session, so it does not matter here.

### Secrets

| Secret | Purpose |
|---|---|
| `POLYGON_API_KEY` | Polygon key with grouped-aggregates access. |
| `DATA_REPO_TOKEN` | PAT with `repo` scope on the **private** `july-backtester-norgate-data` submodule. `GITHUB_TOKEN` is scoped to this repo alone and cannot clone another one, let alone push to it. |
| `DISCORD_WEBHOOK_URL` | Already set. Used only to alert on a failed run. |

### Manual backfill

Use **Actions → Polygon data update → Run workflow** with a `start` date. An
explicit `--start` skips the lookback clamp entirely:

```bash
gh workflow run polygon-daily-update.yml -f start=2026-06-17
```

### The lookback clamp — why unattended runs need it

Without `--start`, the updater picks its start as `min()` over every equity
file's last bar. That minimum is set by **delisted** symbols: roughly 20,873 of
the 35,069 equity files are delisted and frozen as far back as **1990-01-26**,
and they will never receive another bar. Unclamped, a run with no `--start`
therefore asks for every NYSE session since 1990 — **9,557 grouped calls**, with
35k symbols × 9.5k days accumulating in one in-memory dict. That is why this
script had only ever been run by hand with an explicit date range.

`--max-lookback-days` (default **30**) bounds the auto-computed start, so an
unattended run's cost tracks the *schedule* rather than the oldest delisting: a
daily tick fetches one day, and a cron that has been down for a fortnight
recovers on its own. Anything older is a deliberate backfill and must say so.

The clamp bounds the **fetch window only**. Per-symbol writes stay append-only
(each symbol's rows are still filtered to `> its own last bar`), so widening or
narrowing the window can never rewrite history.

### Cost note

Parquet has no in-place append, so each run rewrites every updated file whole,
and Git LFS stores whole blobs with no delta compression. A daily pass therefore
uploads roughly **1.9 GB** of new LFS objects (measured over the ~14,000
currently-listed equity files) — about 40 GB/month of permanent LFS storage
growth on a private repo, plus the same again in bandwidth on every clone.

This is accepted for now. The cheap fix, if it starts to bite, is to leave the
frozen 1990→2026-04-22 Norgate base immutable and write the Polygon continuation
to one consolidated recent-bars file (~100 MB rewritten daily instead of 1.9 GB),
with the `data_provider: "parquet"` loader reading base + continuation.
