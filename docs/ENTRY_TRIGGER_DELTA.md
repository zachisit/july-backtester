# entry_trigger level -> edge: per-strategy trade-count delta (#401)

Universe: 30 large-cap US equities, 2018-01-01 .. 2026-06-30, $100k, 10% allocation,
5% percentage stop. Same data, same strategies, only entry_trigger changed.
Generated 2026-09-21. Reproduce with scripts/entry_trigger_delta.py.

```
Chaikin Money Flow (10d)                        2586    1927    -659   -25.5%
Chaikin Money Flow (20d/0.05/0.05)              1338     774    -564   -42.2%
Daily Overnight Hold (weekdays) w/ VIX Filte    3641    3310    -331    -9.1%
Donchian Breakout (20d/10d)                     1129     681    -448   -39.7%
EMA ADX Combo                                   1090    1090      +0    +0.0%
EMA Crossover (Unfiltered)                       659     331    -328   -49.8%
EMA Crossover w/ SPY+VIX Filter                  505     277    -228   -45.1%
EMA Crossover w/ SPY-Only Filter                 659     331    -328   -49.8%
EMA Crossover w/ VIX-Only Filter                 659     331    -328   -49.8%
EMA Pullback Continuation                        526     526      +0    +0.0%
Gamma Wall Breakout                               57      57      +0    +0.0%
Hold The Week (Tue-Fri)                         4496    3860    -636   -14.1%
Isabella - Chaikin Money Flow                   1338     774    -564   -42.2%
Isabella - Donchian Channel Breakout            1129     681    -448   -39.7%
Isabella - Keltner Channel Breakout             1043     739    -304   -29.1%
Keltner Channel Breakout (20d)                  1043     739    -304   -29.1%
MA Bounce (20d)                                 1950    1414    -536   -27.5%
MA Confluence (Fast Entry & Exit)                915     459    -456   -49.8%
MA Confluence (Fast Entry)                       833     395    -438   -52.6%
MA Confluence (Fast MA Exit)                     866     455    -411   -47.5%
MA Confluence (Full Stack)                       774     373    -401   -51.8%
MA Confluence (Full Stack) w/ Regime Filter      777     660    -117   -15.1%
MA Confluence (Medium MA Exit)                  1408    1007    -401   -28.5%
MACD Crossover (12/26/9)                        2273    1552    -721   -31.7%
MACD+RSI Confirmation                           1859    1392    -467   -25.1%
OBV + Volatility Regime                         2016    1838    -178    -8.8%
OBV Breakout (20d)                               964     721    -243   -25.2%
OBV Trend (20d MA)                              2760    2556    -204    -7.4%
OBV Weighted Momentum                           1966    1802    -164    -8.3%
ORB 5-Min Breakout                                 0       0      +0    +nan%
RS LW 60/15                                      308     308      +0    +0.0%
RSI (14d) w/ SMA200 Filter                       216      99    -117   -54.2%
RSI Mean Reversion (14/30)                       829     388    -441   -53.2%
RSI Mean Reversion (7/20)                        908     527    -381   -42.0%
RSI Oversold MA200 Crossback                     411     304    -107   -26.0%
Relative Strength vs SPY                        1044    1044      +0    +0.0%
SMA 200 Trend Filter (200d)                      482     472     -10    -2.1%
SMA Crossover (20d/50d)                          908     437    -471   -51.9%
SMA Crossover (50d/200d)                         400     142    -258   -64.5%
Stochastic Oscillator (14d)                     2696    1836    -860   -31.9%
Volatility Compression Breakout                  264     197     -67   -25.4%
Volume Spike Reversal                             98      58     -40   -40.8%
Volume-Weighted RSI (14/30)                     1166     563    -603   -51.7%
Weekend Hold (Fri-Mon)                          4184    4140     -44    -1.1%
Williams %R Oversold Bounce (14d/-80/-50)       2710    1835    -875   -32.3%

TOTAL                                          69099   50885  -18214   -26.4%
strategies compared: 59   unchanged: 10   fewer: 49   more: 0

```
