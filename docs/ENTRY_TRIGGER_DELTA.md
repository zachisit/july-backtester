# entry_trigger level → edge: per-strategy trade-count delta (#401)

This compares the number of trades each registered strategy makes under `entry_trigger="level"` and under `"edge"`. Everything else is held fixed: the same data and the same signals, computed once per strategy and reused for both modes. The universe is 30 large-cap US equities from 2018-01-01 to 2026-06-30, with $100k capital, 10% allocation and a 5% percentage stop. The report's `config:` line lists every other setting that moves the numbers.

Regenerated 2026-10-21 using the corrected delta runner at `c802162b` (#405), with the same engine code as `b66a8412`. The report below is the script's exact `--out` file. The runner now supplies each ticker and applies explicit strategy parameters after injected arguments, matching the production call order.

## What a public checkout can reproduce

The **38 public rows and the "public only" total (55,335 → 39,285, −29.0%)** are computed only from code in the public repo. The prices are not public, though. `--corpus` defaults to `parquet_data/data`, the licensed per-symbol parquet corpus, which is a private submodule and isn't in a public clone. Without it, the script loads 0/30 symbols.

So the exact row values need that corpus. A different data source gives approximately the same answer: @shardul0701 re-ran it on the `data_gate` corpus plus overlay and got 55,291 → 39,242, also −29.0%, with 14 of the 28 rows he could match exactly and the largest difference 53 trades.

To regenerate from a full checkout, run `python scripts/entry_trigger_delta.py --hide-private --out <file>`.

The census also includes 99 strategies from the private submodule, which isn't available in a public checkout. Only successfully exercised strategies contribute to trade totals. Private strategies appear here only as aggregate counts and are never named. `--hide-private` enforces that, and `tests/test_entry_trigger_delta_script.py` checks that strategies are tagged public or private by their source file.

## Reading it

- **Every public strategy trades less under edge: 38 of 38 fewer, 0 unchanged.** The size of the drop tracks how the strategy's signal is built. State-shaped signals move a lot: the EMA/SMA crossovers and the unfiltered MA Confluence variants drop 45–65% (the regime-filtered and medium-exit confluence variants drop 15% and 29%), and Bollinger fade drops 45–47%. Pulse-like and calendar signals barely move: `Weekend Hold` −1.1%, `SMA 200 Trend Filter` −2.1%, `OBV Trend` −7.4%. So the effect is a gradient, not a split into "affected" and "unaffected" strategies.
- **The 10 unchanged strategies are all private.** No public strategy is unchanged, so this report makes no claim about signal shape that a public reader can't check.
- **Edge can add trades as well as remove them.** One private strategy trades *more* under edge. That's the capacity re-plan effect noted in `config.py`: skipping a late entry frees capital for another symbol. It is real but rare on this book.
- **Strategies that never traded are excluded.** "Not exercised" strategies (0 trades in both modes) are left out of the counts, because 0 = 0 says nothing about the semantics. Errors are listed rather than dropped. A symbol that fails at the signal stage is missing from both modes' books, never from just one.

## Audit correction and private coverage

The old runner omitted `symbol`, which the normal pipeline always supplies. The corrected call exposes **41 private signal-stage failures**: 40 strategies reject the existing production `symbol` keyword, and one fails later with an `AttributeError` inside its logic. All 41 also fail before reaching the simulator under the normal pipeline on both base `d22f6695` and head `c802162b`; a positive control reaches the simulator on both. These are existing private implementation incompatibilities, rather than an effect of changing `entry_trigger`.

Consequently the corrected report compares 90 strategies (38 public and 52 private), with six unexercised and 41 errored private strategies explicitly excluded. The older combined/private totals used a different call contract and are superseded. All 38 public rows and their total reproduce exactly. Private strategy names remain omitted.

The public default suite passed (2,838 tests), and all 101 local private tests passed. That private suite does not cover the full registry: its passing result does not establish that the 41 excluded strategies can run through the production pipeline.

## Report

```
universe: 30/30 symbols, 2018-01-01..2026-06-30, $100,000, 10% allocation, 5% percentage stop
config: execution_time='open', slippage_pct=0.0005, commission_per_share=0.002, max_pct_adv=0.05, volume_impact_coeff=0.0, entry_priority='alphabetical', position_sizing_method='fixed', max_portfolio_heat=0.1, timeframe='D', timeframe_multiplier=1
strategies registered: 137  (38 public, 99 private)

strategy                                             src       level    edge   delta      pct
ATR Trailing Stop (14/3)                             public      745     487    -258   -34.6%
ATR Trailing Stop w/ Trend Filter                    public     1024     693    -331   -32.3%
Bollinger Band Breakout (20d)                        public     1282     873    -409   -31.9%
Bollinger Band Fade (20d/2.0)                        public     1791     987    -804   -44.9%
Bollinger Band Fade (20d/2.5)                        public      992     527    -465   -46.9%
Bollinger Band Fade w/ SPY Trend Filter (20d/2.0)    public     1791     987    -804   -44.9%
Bollinger Band Squeeze (20d/40d)                     public      308     257     -51   -16.6%
Bollinger Mean Reversion w/ ATR Stop (20d/2.0/2xATR) public     1773    1211    -562   -31.7%
Chaikin Money Flow (10d)                             public     2586    1927    -659   -25.5%
Chaikin Money Flow (20d/0.05/0.05)                   public     1338     774    -564   -42.2%
Daily Overnight Hold (weekdays) w/ VIX Filter        public     3641    3310    -331    -9.1%
Donchian Breakout (20d/10d)                          public     1129     681    -448   -39.7%
EMA Crossover (Unfiltered)                           public      659     331    -328   -49.8%
EMA Crossover w/ SPY+VIX Filter                      public      505     277    -228   -45.1%
EMA Crossover w/ SPY-Only Filter                     public      659     331    -328   -49.8%
EMA Crossover w/ VIX-Only Filter                     public      659     331    -328   -49.8%
Hold The Week (Tue-Fri)                              public     4496    3860    -636   -14.1%
Keltner Channel Breakout (20d)                       public     1043     739    -304   -29.1%
MA Bounce (20d)                                      public     1950    1414    -536   -27.5%
MA Confluence (Fast Entry & Exit)                    public      915     459    -456   -49.8%
MA Confluence (Fast Entry)                           public      833     395    -438   -52.6%
MA Confluence (Fast MA Exit)                         public      866     455    -411   -47.5%
MA Confluence (Full Stack)                           public      774     373    -401   -51.8%
MA Confluence (Full Stack) w/ Regime Filter          public      777     660    -117   -15.1%
MA Confluence (Medium MA Exit)                       public     1408    1007    -401   -28.5%
MACD Crossover (12/26/9)                             public     2273    1552    -721   -31.7%
MACD+RSI Confirmation                                public     1859    1392    -467   -25.1%
OBV Trend (20d MA)                                   public     2760    2556    -204    -7.4%
RSI (14d) w/ SMA200 Filter                           public      216      99    -117   -54.2%
RSI Mean Reversion (14/30)                           public      829     388    -441   -53.2%
RSI Mean Reversion (7/20)                            public      908     527    -381   -42.0%
SMA 200 Trend Filter (200d)                          public      482     472     -10    -2.1%
SMA Crossover (20d/50d)                              public      908     437    -471   -51.9%
SMA Crossover (50d/200d)                             public      400     142    -258   -64.5%
Stochastic Oscillator (14d)                          public     2696    1836    -860   -31.9%
Volume-Weighted RSI (14/30)                          public     1166     563    -603   -51.7%
Weekend Hold (Fri-Mon)                               public     4184    4140     -44    -1.1%
Williams %R Oversold Bounce (14d/-80/-50)            public     2710    1835    -875   -32.3%

TOTAL (all)                                                   117881   88905  -28976   -24.6%
                                                             compared 90   unchanged 10   fewer 79   more 1
TOTAL (public only)                                            55335   39285  -16050   -29.0%
                                                             compared 38   unchanged 0   fewer 38   more 0
TOTAL (private only)                                           62546   49620  -12926   -20.7%
                                                             compared 52   unchanged 10   fewer 41   more 1

unchanged (level == edge, > 0 trades): 10 private (not named)
not exercised (0 trades in both modes, excluded from counts): 6 private (not named)
errors, signal or simulation (excluded, listed): 41 private (not named)
signal-stage symbol failures: 1230 across 41 strategies
```
