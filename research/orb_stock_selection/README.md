# Research: Opening Range Breakout (ORB) — stock-selection variant

**Question:** A viral X post ([@ThiccTeddy](https://x.com/ThiccTeddy)) claims the Opening Range
Breakout is *"the best day trading strategy on the planet … IT. WORKS."* Does it survive a
faithful, cost-aware backtest?

**One-line answer:** The signal has a **real gross edge** (Sharpe ~1.2, +2,080% before costs), but
that edge is **microscopic per trade and fully consumed by transaction costs** on the volatile,
low-priced names the strategy selects. Net break-even sits at **~4 bps of slippage per side** — and
the strategy trades $5–30 crypto miners where realistic slippage is 10–30 bps. **Net verdict: a
real pattern, but a net loser at retail execution in the 2021–2026 regime.**

---

## Grounding — this isn't pure hype

ORB has genuine peer-reviewed support:
- **Zarattini & Aziz (2023),** *"Can Day Trading Really Be Profitable?"* — 5-min ORB on QQQ 2016–2023,
  strong risk-adjusted returns, especially leveraged (TQQQ).
- **Zarattini, Barbon & Aziz (2024),** *"A Profitable Day Trading Strategy For The U.S. Equity
  Market"* — a daily **high-relative-volume stock screen → intraday 5-min ORB** on the day's movers.

We tested the **2024 stock-selection variant** (the most rigorous, strongest published version), not
the naïve long-only-no-stop version loosely pictured in the post.

## Methodology (faithful to the 2024 paper)

**Stage 1 — daily "stocks in play" screen** (`scripts/orb_stock_selection_research.py`)
- Universe: `tickers_to_scan/high_volatility.json` — 242 curated liquid high-beta names
  (mover-heavy: MARA, RIOT, COIN, CLSK, HUT, UPST, AFRM, CVNA, IONQ …), a truer proxy for "stocks in
  play" than a mega-cap-heavy S&P 500.
- **Look-ahead-free:** ranking by a day's *total* volume would peek at the future. Instead we apply
  liquidity filters (price > $5, prior-20d ADV > 1M shares, ATR) and rank by **|gap %| at the open**
  (the classic, at-09:30-knowable "in play" signal). Top-20 per session.
- Result: 20 picks/session over **1,218 sessions**, median gap **3.1%** — a faithful mover screen.

**Stage 2 — intraday 5-min ORB** (`scripts/orb_stage2_backtest.py`)
- Opening range = **first 5-min candle** (09:30–09:35 ET, RTH only).
- Direction: bullish candle → **long** on break of OR high; bearish → **short** on break of OR low;
  doji (|body| < 10% of range) → skip.
- **Stop** = opposite extreme of the OR candle. **Size to risk 1% of equity** per trade
  (4× intraday leverage cap, buying power split across the day's 20 picks).
- **Exit** = first of {stop, **10R target**, EOD close}. Stop checked before target within a bar
  (conservative). Commissions ($0.0005/share) + slippage both sides. Compounded from $25,000.

## Data constraint (important)

Polygon 5-min history on the current plan starts **2021-07-12**, so the test window is
**2021-08 → 2026-06 (1,218 sessions)** — no COVID crash, no 2018, no GFC. This is a **harder,
different** window than the papers' 2016–2023, and it *starts at the post-meme momentum top* and runs
through the 2022 bear that gutted exactly these high-beta / crypto-miner names.

## Results

Headline (base case: IBKR commission + 5 bps slippage/side, 18,952 trades):

| Strategy | Total | CAGR | Sharpe | MaxDD | Calmar |
|---|---|---|---|---|---|
| **ORB (1% risk, 10R)** | **−54.5%** | −15.0% | 0.02 | −77.1% | −0.19 |
| SPY buy & hold | +70.7% | 11.7% | 0.49 | −25.4% | 0.46 |
| QQQ buy & hold | +101.8% | 15.7% | 0.57 | −35.6% | 0.44 |

**Cost sensitivity — the whole story.** The signal *works gross*; costs eat it:

| Cost scenario (per side) | Total | CAGR | Sharpe | Profit factor | avg R / trade |
|---|---|---|---|---|---|
| **Zero cost** (raw signal) | **+2,080%** | 89.2% | 1.19 | 1.08 | +0.022 |
| 2 bps slip, no commission | +396% | 39.3% | 0.74 | 1.04 | +0.014 |
| IBKR comm + 2 bps | +316% | 34.3% | 0.69 | 1.04 | +0.013 |
| IBKR comm + 3 bps | +99% | 15.3% | 0.47 | 1.02 | +0.009 |
| **IBKR comm + 4 bps** (break-even) | **−5%** | −1.0% | 0.24 | **1.00** | +0.005 |
| IBKR comm + 5 bps (base) | −54.5% | −15.0% | 0.02 | 0.98 | +0.001 |
| IBKR comm + 10 bps (stress) | −98.9% | −60.4% | −1.09 | 0.88 | −0.018 |

Win rate is ~40% throughout; the edge is a tiny positive expectancy per trade
(**+0.022R gross**) that flips negative once you pay to cross the spread.

## Interpretation

1. **The pattern is real.** Zero-cost Sharpe 1.19 and +2,080% vs QQQ's +102% *confirms* the paper's
   core claim that ORB carries genuine gross alpha. ThiccTeddy is not making it up.
2. **The edge lives inside the spread.** Break-even is ~4 bps/side. The strategy selects $5–30
   crypto miners and high-beta movers where realistic market/stop-order slippage is routinely
   **10–30+ bps**. At any honest retail execution assumption, it is a **net loser** in this window.
3. **Why the paper looks better:** (a) 2016–2023 included the explosive 2020–2021 momentum regime
   that is extraordinarily kind to long breakouts; our window starts at that top. (b) Published
   headline results lean on leverage and optimistic fills. Change the window and price in realistic
   slippage and the net edge evaporates.

## Limitations / honest caveats

- **Universe is an approximation** — we screen within 242 liquid names, not the whole market. This
  likely *understates* the gross edge (the paper's best movers are smaller gappers) **and**
  *overstates* net results (those smaller names have even worse slippage). Directionally the net
  conclusion is robust.
- Single window (2021–2026), no walk-forward / Monte-Carlo yet; no short-borrow / hard-to-borrow
  cost modeled (would hurt the short side further); intrabar stop-before-target is a conservative
  assumption.

## Verdict

ThiccTeddy's *"it works"* is **half true**: the opening-range breakout is a **real gross pattern**,
not a myth. But *"best day trading strategy on the planet"* does **not** survive realistic costs on
the names it trades — in 2021–2026 it's a **net loser after ~4 bps of slippage**, while buy-and-hold
made +70–100%. The honest framing: *ORB is an edge that belongs to your broker, not to you*, unless
you can genuinely trade it at institutional-grade execution.

---

*Reproduce:* `rtk .venv/bin/python scripts/orb_stock_selection_research.py` (screen) then
`rtk .venv/bin/python scripts/orb_stage2_backtest.py` (backtest; override `ORB_SLIPPAGE_PCT` /
`ORB_COMMISSION_PS` for the sensitivity sweep). Equity curve: `equity_curve.csv`.
