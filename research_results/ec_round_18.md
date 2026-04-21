# EC-R18: Percentage Entry Stop Test — INEFFECTIVE
**Date:** 2026-04-17
**Run ID:** ec-r18-pct-stops_2026-04-17_15-06-28

## Hypothesis
Add a fixed percentage stop from entry (8%, 10%, 12%) to MA Bounce + Low-Vol.
Unlike ATR trailing stop (which churn low-vol stocks), a percentage stop from
entry only fires when price moves adversely from the entry point. Hypothesis:
cuts genuine losers early while letting winners (like BA +145%) run freely.

## Results

| Strategy | Calmar | Sharpe | MaxDD | OOS P&L | Trades | WFA |
|---|---|---|---|---|---|---|
| No stop (baseline) | 0.38 | 0.17 | 16.30% | +92.00% | 4089 | Pass 3/3 |
| 8% stop from entry | 0.35 | 0.13 | 16.75% | +76.38% | 4128 | Pass 3/3 |
| 10% stop from entry | 0.36 | 0.15 | 16.39% | +87.52% | 4109 | Pass 3/3 |
| 12% stop from entry | 0.36 | 0.14 | 16.42% | +85.29% | 4100 | Pass 3/3 |

All MC Score 5, WFA Pass (3/3). Correlation r=0.98 (all variants nearly identical to baseline).

## Why Percentage Stops Are Ineffective Here

**The stop almost never fires:**
- Trade count barely changes (4089 → 4100-4128 extra trades)
- 39 extra trades at 10% stop = only 20 additional stop-outs over 21 years

**Why the stop doesn't fire:**
1. MA Bounce enters AFTER 3-bar confirmed upward reversal from MA support
2. By the time the strategy enters, the stock has already shown upward momentum
3. For a low-vol stock (ATR 2.0-2.5%), an 8% adverse move = 3.2-4.0 ATR events
4. Genuine 8% pullbacks after a confirmed bounce are extremely rare for low-vol stocks
5. Natural exit fires first (price falls below SMA200 or SPY gate closes)

**Slight performance degradation on all stop variants:**
- All stops reduce OOS P&L (92% → 76-87%)
- All stops reduce Calmar (0.38 → 0.35-0.36)
- No stop variant improves over baseline

**The stop adds friction but no benefit:**
- When the stop fires (rarely), it books a loss slightly earlier than the natural exit would
- The commission on the stop exit + immediate re-entry (strategy still signals 1) = cost
- Net effect: tiny performance drag with no drawdown improvement

## Key Insight

**MA Bounce's natural exit mechanism is already effective at loss-cutting:**
- Natural exit fires when: bounce_signal turns -1 (price moves away from MA) OR
  SMA200 gate fails (stock turns bearish) OR SPY gate fails (macro turns bearish)
- For low-vol stocks in uptrend, these natural exits handle loss-cutting adequately
- A percentage stop from entry adds nothing because the natural exits are faster

**The outlier profitable trades (BA +145%) are NOT losses from any perspective.**
They don't cause drawdowns — they cause upward SPIKES on exit. A stop from entry
would not affect them (BA never returned to its entry price during the 440-bar hold).

## Summary of Dead Ends (EC-R14 through EC-R18)

All five modification attempts made the strategy WORSE:

| Round | Modification | Verdict |
|---|---|---|
| EC-R14 | 1.5% ATR threshold | Overfitted — kills setups |
| EC-R14 | SMA200 + Low-Vol combined | Degrades Calmar 0.61 → 0.41 |
| EC-R15 | 3% allocation | Cash drag kills CAGR below hurdle |
| EC-R16 | ETF-only universe | Too few trades, same cash drag |
| EC-R17 | ATR trailing stop | Catastrophic churn (4089 → 10163 trades) |
| EC-R18 | Percentage entry stop | Inert — almost never fires |

## Research Conclusion

**The EC-R13 winner is the best achievable result with the current architecture:**
- MA Bounce + Low-Vol ATR Filter (2.5%) + SMA200 Gate + SPY SMA96 Gate
- 5% allocation, 46-symbol universe (sectors+DJI)
- No stop loss

Metrics: Calmar 0.38, MaxDD 16.30%, OOS +92%, Trades 4089, MC Score 5, WFA Pass (3/3)
Rolling Sharpe avg: 0.06, MaxRcvry: 1151d (3.2 years max drawdown duration)

## Direction for EC-R19

**Champion PDF generation and visual assessment.**
Run final champion configuration and inspect tearsheets to determine if the curve is
visually smooth enough for the stated goal, or identify a genuinely new architectural
approach (e.g., expanding to S&P 500 universe via Norgate watchlist).
