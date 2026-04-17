# EC-R17: ATR Trailing Stop Test — REGRESSION (Churn Disaster)
**Date:** 2026-04-17
**Run ID:** ec-r17-atr-stops_2026-04-17_15-00-42

## Hypothesis
Add ATR-based trailing stop to MA Bounce + Low-Vol to force earlier exits on winning positions.
Expected: BA-type 440-bar trade exits sooner → smaller portfolio spike on exit.
- 3× ATR(14) stop = 7.5% trail for a 2.5%-ATR stock
- 2× ATR(14) stop = 5.0% trail for a 2.5%-ATR stock

## Results

| Strategy | Calmar | Sharpe | MaxDD | OOS P&L | Trades | WFA |
|---|---|---|---|---|---|---|
| MA Bounce + Low-Vol, No Stop (baseline) | 0.38 | 0.17 | 16.30% | +92.00% | 4089 | Pass 3/3 |
| MA Bounce + Low-Vol, 3× ATR Stop | 0.05 | -0.30 | 31.47% | +11.90% | 6510 | Pass 2/3 |
| MA Bounce + Low-Vol, 2× ATR Stop | -0.06 | -0.87 | 66.19% | -6.44% | 10163 | Pass 3/3 |

## Why ATR Trailing Stops Fail for This Strategy

**ATR trailing stop + low-vol filter = self-defeating combination:**
- Strategy selects stocks where ATR_14/Close < 2.5%
- At 2.5% ATR: 3× stop = 7.5% trail, 2× stop = 5.0% trail
- These gaps are within normal daily noise for a stock in a mild bounce
- Result: stop fires during normal price oscillation → rapid re-entry → churn

**Trade count explosion confirms the churn:**
- No stop: 4,089 trades (21 years baseline)
- 3× ATR: 6,510 trades (+59%)
- 2× ATR: 10,163 trades (+149%)

Each stop-out → re-entry creates a new "trade" with double commissions ($0.004/share × 2).
At 10,163 trades vs 4,089, commission drag alone explains much of the -87% Sharpe hit.

**MaxDD exploded instead of improving:**
- 2× ATR stop: MaxDD 66.19% (vs 16.30% baseline)
- The rapid re-entries in sideways/weak markets compound losses before the stop fires again

**ATR stops work for TREND strategies** (where the stop only fires after large adverse moves),
NOT for mean-reversion strategies (where the price naturally oscillates near the MA).

## Critical Insight

**Mean-reversion + trailing stop = structural incompatibility:**
MA Bounce is a mean-reversion strategy. It enters when price PULLS BACK to the MA.
By design, the price oscillates near the MA on entry. A tight trailing stop will fire
before the mean-reversion "bounce" has time to develop. Trailing stops require directional
momentum, not oscillation.

**For trailing stops to work on MA Bounce, the multiplier would need to be 8-10× ATR**
(large enough to survive the initial pullback). At 10× ATR on a 2.5% stock = 25% trail.
This is no longer a meaningful exit rule — it's just an emergency stop.

## Direction for EC-R18

**Test percentage-based ENTRY stop (not trailing) at 8%, 10%, 12% from entry:**
- Fixed stop from ENTRY PRICE (not from current high/trailing)
- Cuts losers that move immediately against us
- Does NOT interfere with winners — once BA is up 20%, the 10% entry stop is irrelevant
- Hypothesis: win rate stays stable, but average loss per trade shrinks → better Sharpe

This is fundamentally different from a trailing stop:
- Trailing stop: moves up with price, fires at X% below RECENT HIGH
- Entry stop: fixed at entry price −X%, fires if price drops X% from WHERE WE ENTERED

For MA Bounce entering at a MA pullback, an 8-10% entry stop would only fire on
names that failed to bounce (genuine losers), not on oscillating winners.
