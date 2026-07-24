# Rsi Divergence V2 Trend+Confirm W  2.0X Atr14 Sl
---

## Data Cleaning Summary

```text
Initial trades loaded: 88
Rows dropped due to NaN in critical columns (Profit, % Profit, Date, Ex. date): 0
NaN Counts per Critical Column:
Profit      0
% Profit    0
Date        0
Ex. date    0

Sample of Dropped/Problematic Rows (if any):
None (No rows dropped)

Final Trade Count for Analysis: 88
```

## Overall Performance Metrics

```text
Total Net Profit:                             $28,507.29
Total Trades:                                 88
Total Shares Purchased:                       11,574
Strategy Total Return:                        28.51%

Gross Profit:                                 $71,554.17
Gross Loss:                                   $-43,046.88
Profit Factor:                                1.66

Win Rate:                                     38.64%
Average Winning Trade:                        $2,104.53
Average Losing Trade:                         $-797.16
Average Trade Profit:                         $323.95
Ratio Avg Win / Avg Loss:                     2.64

Max Consecutive Wins:                         4
Max Consecutive Losses:                       9

Expectancy per Trade:                         $323.95

Total Duration:                               5.00 years (1827 days)
Average Trades per Year:                      17.6
CAGR:                                         5.14%
Estimated After-Tax CAGR (30% tax):           3.70%
Annual Turnover:                              193.77%

Sharpe Ratio (Ann., Portfolio Daily, Rf=5.0%): 0.08
Sortino Ratio (Ann., Portfolio Daily, Rf=5.0%): 0.10
Calmar Ratio (CAGR / Max Equity DD%):         0.42
Max Equity Drawdown:                          12.25%

Sharpe (Per Trade, Arith Ret, Non-Ann, Rf=0%): 0.15
Sharpe (Per Trade, Log Ret, Non-Ann, Rf=0%):  0.09

Tail Risk Analysis (Based on Trade Profit $):
--------------------------------------------------
95% Value at Risk (VaR):                      $-1,761.65
95% Conditional VaR (CVaR):                   $-2,193.25
99% Value at Risk (VaR):                      $-2,244.44
99% Conditional VaR (CVaR):                   $-3,109.29

Benchmark Comparison (SPY):
--------------------------------------------------
SPY Buy & Hold Return (period):               N/A
Beta vs SPY:                                  N/A
Alpha vs SPY (Ann., Rf=5.0%):                 N/A
```

## Walk-Forward Analysis (WFA)

```text
Split Ratio   : 80% In-Sample / 20% Out-of-Sample
IS/OOS Boundary : 2025-10-27

OOS P&L (% of capital):                       +22.66%
WFA Verdict:                                  Pass

Result: Out-of-Sample performance is consistent with In-Sample. No overfitting signal detected.
```

## Strategy Verdict

```text
No strategy verdict available — llm_verdict.json not found or no matching entry.
```

## Detailed Drawdown Analysis

```text
Max System Drawdown (Based on Equity %):      -12.25%

Drawdown Duration & Recovery Periods (Based on Cumulative Profit Peaks/Troughs):
---------------------------------------------------------------------------
Average Drawdown Duration (Trades):           10.5
Maximum Drawdown Duration (Trades):           38
Average Drawdown Duration (Days):             160
Maximum Drawdown Duration (Days):             602

Average Recovery Time (Trades):               4.7
Maximum Recovery Time (Trades):               17
Average Recovery Time (Days):                 80
Maximum Recovery Time (Days):                 308

Definitions:
 - Duration: Time from equity peak to new equity peak.
 - Recovery Time: Time from drawdown trough to new equity peak.


Top 5 Largest Drawdown Periods (by $ Amount, based on Cum. Profit Peaks):
------------------------------------------------------------------------------------------
Start Date   Trough Date  End Date     Duration(d)   DD Amount($)    Peak Val($)    
------------------------------------------------------------------------------------
2024-07-14   2025-08-24   2026-03-08   602           12,188.33       17,539.86      
2022-12-18   2023-05-14   2024-03-17   454           7,809.48        -966.62        
2026-05-10   2026-06-07   2026-06-21   42            4,373.06        17,741.52      
2026-06-21   2026-07-19   Ongoing      28            1,452.71        29,752.69      
2024-04-14   2024-04-14   2024-04-21   7             1,192.44        3,482.29
```

## Performance per Symbol Analysis

```text
Performance per Symbol (Sorted by Win Rate):
================================================================================
       Total_Trades Total_Profit Win_Rate Avg_Profit   Avg_Loss Profit_Factor Avg_Pct_Return Avg_Bars_Held
Symbol                                                                                                    
ADI               1    $2,445.11   100.0%  $2,445.11      $0.00           inf         21.96%          91.0
CRWD              1       $84.11   100.0%     $84.11      $0.00           inf          0.76%          77.0
ON                1      $758.53   100.0%    $758.53      $0.00           inf          6.54%          56.0
ODFL              1    $1,223.52   100.0%  $1,223.52      $0.00           inf         10.90%          84.0
QCOM              1    $4,765.06   100.0%  $4,765.06      $0.00           inf         48.77%         237.0
MNST              1      $150.93   100.0%    $150.93      $0.00           inf          1.60%         119.0
ROP               1    $1,888.17   100.0%  $1,888.17      $0.00           inf         18.88%         496.0
KLAC              1    $7,761.87   100.0%  $7,761.87      $0.00           inf         70.22%         238.0
IDXX              1      $545.64   100.0%    $545.64      $0.00           inf          5.46%         188.0
FTNT              1    $3,389.85   100.0%  $3,389.85      $0.00           inf         29.70%         182.0
FAST              1    $1,294.88   100.0%  $1,294.88      $0.00           inf         11.69%         140.0
TEAM              1      $275.69   100.0%    $275.69      $0.00           inf          2.24%           7.0
CTSH              1      $605.76   100.0%    $605.76      $0.00           inf          5.26%         182.0
CSX               1      $459.54   100.0%    $459.54      $0.00           inf          9.13%         132.0
CSCO              1    $2,089.33   100.0%  $2,089.33      $0.00           inf         18.15%         196.0
DDOG              1       $37.93   100.0%     $37.93      $0.00           inf          0.39%          77.0
AMAT              1    $4,392.18   100.0%  $4,392.18      $0.00           inf         44.37%         230.0
CEG               1    $6,010.11   100.0%  $6,010.11      $0.00           inf         53.65%         111.0
AMD               1    $5,351.07   100.0%  $5,351.07      $0.00           inf         55.95%         133.0
CDW               2    $1,247.92   100.0%    $623.96      $0.00           inf          6.12%          73.0
AMZN              1    $1,692.54   100.0%  $1,692.54      $0.00           inf         17.32%         153.0
CCEP              1      $505.57   100.0%    $505.57      $0.00           inf          3.87%          21.0
ASML              1    $1,039.13   100.0%  $1,039.13      $0.00           inf         10.39%         244.0
CPRT              2     $-922.07    50.0%     $31.35   $-953.42          0.03         -4.14%          31.5
AEP               2      $420.72    50.0%    $707.87   $-287.14          2.47          1.50%          52.0
PANW              2    $1,915.11    50.0%  $1,950.06    $-34.96         55.78         10.07%         136.0
MSTR              2      $127.86    50.0%  $1,236.22 $-1,108.36          1.12          0.96%          49.0
ARM               2   $14,572.23    50.0% $16,384.23 $-1,812.00          9.04         61.33%          52.5
KDP               2     $-330.75    50.0%    $383.37   $-714.12          0.54         -0.75%          21.0
PAYX              2     $-199.47    50.0%    $366.94   $-566.41          0.65         -0.43%          45.5
SHOP              2      $663.85    50.0%  $1,403.81   $-739.97          1.90          3.94%          45.5
HON               3     $-396.24    33.3%    $486.60   $-441.42          0.55         -1.56%          55.7
INTC              3   $-2,691.82    33.3%    $589.28 $-1,640.55          0.18         -8.35%          23.3
WDAY              1   $-1,015.71     0.0%      $0.00 $-1,015.71          0.00         -8.90%          56.0
TTD               1     $-995.31     0.0%      $0.00   $-995.31          0.00         -8.08%          70.0
SBUX              2     $-604.40     0.0%      $0.00   $-302.20          0.00         -2.66%          63.0
XEL               1     $-335.56     0.0%      $0.00   $-335.56          0.00         -3.51%           7.0
ROST              1     $-319.08     0.0%      $0.00   $-319.08          0.00         -3.26%           7.0
VRTX              1     $-966.62     0.0%      $0.00   $-966.62          0.00         -9.67%          14.0
VRSK              3   $-1,921.87     0.0%      $0.00   $-640.62          0.00         -5.43%          23.3
PDD               2     $-966.86     0.0%      $0.00   $-483.43          0.00         -4.50%          49.0
PLTR              1   $-1,837.01     0.0%      $0.00 $-1,837.01          0.00        -19.22%          21.0
PEP               2     $-874.03     0.0%      $0.00   $-437.01          0.00         -3.84%          31.5
TRI               1     $-529.82     0.0%      $0.00   $-529.82          0.00         -4.09%           0.0
TSLA              1   $-1,668.15     0.0%      $0.00 $-1,668.15          0.00        -15.06%          21.0
TTWO              2   $-1,896.69     0.0%      $0.00   $-948.35          0.00         -7.52%          28.0
ISRG              1   $-1,234.87     0.0%      $0.00 $-1,234.87          0.00        -12.35%          77.0
NFLX              1     $-308.28     0.0%      $0.00   $-308.28          0.00         -3.08%          91.0
CSGP              2   $-2,648.95     0.0%      $0.00 $-1,324.48          0.00        -11.07%          21.0
AXON              1     $-289.21     0.0%      $0.00   $-289.21          0.00         -2.61%          63.0
BIIB              1      $-45.77     0.0%      $0.00    $-45.77          0.00         -0.42%          70.0
BKNG              1     $-272.65     0.0%      $0.00   $-272.65          0.00         -2.46%         140.0
CDNS              1   $-1,122.81     0.0%      $0.00 $-1,122.81          0.00        -10.13%          14.0
CHTR              1     $-578.61     0.0%      $0.00   $-578.61          0.00         -4.61%          20.0
COST              1     $-527.33     0.0%      $0.00   $-527.33          0.00         -4.76%          56.0
CTAS              2     $-842.39     0.0%      $0.00   $-421.20          0.00         -3.66%          49.0
MU                1     $-456.84     0.0%      $0.00   $-456.84          0.00         -3.99%           7.0
EXC               1     $-720.62     0.0%      $0.00   $-720.62          0.00         -5.78%          55.0
FANG              1     $-919.96     0.0%      $0.00   $-919.96          0.00         -9.09%          21.0
GILD              2   $-1,223.91     0.0%      $0.00   $-611.95          0.00         -5.97%           7.0
LIN               2   $-1,439.02     0.0%      $0.00   $-719.51          0.00         -6.96%          77.0
MDLZ              2     $-902.15     0.0%      $0.00   $-451.07          0.00         -3.93%          31.5
MRVL              1   $-2,092.77     0.0%      $0.00 $-2,092.77          0.00        -17.38%          56.0
ZS                1   $-3,109.29     0.0%      $0.00 $-3,109.29          0.00        -23.26%           7.0

Symbols with Profit Factor < 1.00 (Sorted by PF):
================================================================================
       Total_Trades Total_Profit Win_Rate Profit_Factor
Symbol                                                 
TTWO              2   $-1,896.69     0.0%          0.00
CSGP              2   $-2,648.95     0.0%          0.00
AXON              1     $-289.21     0.0%          0.00
BIIB              1      $-45.77     0.0%          0.00
BKNG              1     $-272.65     0.0%          0.00
CDNS              1   $-1,122.81     0.0%          0.00
CHTR              1     $-578.61     0.0%          0.00
NFLX              1     $-308.28     0.0%          0.00
COST              1     $-527.33     0.0%          0.00
MU                1     $-456.84     0.0%          0.00
EXC               1     $-720.62     0.0%          0.00
FANG              1     $-919.96     0.0%          0.00
GILD              2   $-1,223.91     0.0%          0.00
LIN               2   $-1,439.02     0.0%          0.00
MDLZ              2     $-902.15     0.0%          0.00
CTAS              2     $-842.39     0.0%          0.00
ISRG              1   $-1,234.87     0.0%          0.00
ZS                1   $-3,109.29     0.0%          0.00
TSLA              1   $-1,668.15     0.0%          0.00
WDAY              1   $-1,015.71     0.0%          0.00
TTD               1     $-995.31     0.0%          0.00
SBUX              2     $-604.40     0.0%          0.00
MRVL              1   $-2,092.77     0.0%          0.00
ROST              1     $-319.08     0.0%          0.00
XEL               1     $-335.56     0.0%          0.00
VRSK              3   $-1,921.87     0.0%          0.00
PDD               2     $-966.86     0.0%          0.00
PLTR              1   $-1,837.01     0.0%          0.00
PEP               2     $-874.03     0.0%          0.00
TRI               1     $-529.82     0.0%          0.00
VRTX              1     $-966.62     0.0%          0.00
CPRT              2     $-922.07    50.0%          0.03
INTC              3   $-2,691.82    33.3%          0.18
KDP               2     $-330.75    50.0%          0.54
HON               3     $-396.24    33.3%          0.55
PAYX              2     $-199.47    50.0%          0.65
```

## Profitable vs. Unprofitable Symbol Comparison

```text
Comparison based on PF >= 1.50 vs PF < 1.00

Profitable Symbols (27 symbols, 32 trades):
  Avg % Profit per Trade: 19.16%
  Avg Bars Held: 128.50
  Overall Win Rate: 87.50%

Unprofitable Symbols (36 symbols, 54 trades):
  Avg % Profit per Trade: -6.08%
  Avg Bars Held: 38.70
  Overall Win Rate: 9.26%

Interpretation Notes:
- Compare Avg Bars Held, Avg % Profit, Win Rate between groups.
```

## Monthly Net Profit Plot

![Monthly Net Profit Plot](images/monthly_net_profit_plot_1.png)

## Top 5 Losing Symbol Contributors During Losing Months

```text
Month: 2022-12 (Total Loss: $-1,380.29)
 Symbol  Contribution
   ISRG    $-1,234.87
   VRTX      $-966.62
    LIN      $-953.56
    HON      $-844.72
    PDD      $-545.19

Month: 2023-01 (Total Loss: $-919.96)
 Symbol  Contribution
   FANG      $-919.96

Month: 2023-04 (Total Loss: $-1,014.95)
 Symbol  Contribution
   INTC    $-1,165.89

Month: 2023-07 (Total Loss: $-964.28)
 Symbol  Contribution
   MSTR    $-1,108.36
   ROST      $-319.08
    AEP      $-287.14

Month: 2024-03 (Total Loss: $-1,192.44)
 Symbol  Contribution
   CSGP    $-1,192.44

Month: 2024-05 (Total Loss: $-3,654.48)
 Symbol  Contribution
   MRVL    $-2,092.77
    TTD      $-995.31
   PAYX      $-566.41

Month: 2024-06 (Total Loss: $-1,043.47)
 Symbol  Contribution
   TTWO      $-632.92
   GILD      $-410.55

Month: 2024-11 (Total Loss: $-905.05)
 Symbol  Contribution
   VRSK      $-905.05

Month: 2024-12 (Total Loss: $-1,456.51)
 Symbol  Contribution
   CSGP    $-1,456.51

Month: 2025-01 (Total Loss: $-1,560.36)
 Symbol  Contribution
    ARM    $-1,812.00

Month: 2025-02 (Total Loss: $-2,536.88)
 Symbol  Contribution
   INTC    $-2,115.21
    PDD      $-421.68

Month: 2025-05 (Total Loss: $-4,126.33)
 Symbol  Contribution
   TSLA    $-1,668.15
   CDNS    $-1,122.81
   CPRT      $-953.42
   CTAS      $-633.62
   COST      $-527.33

Month: 2025-07 (Total Loss: $-308.85)
 Symbol  Contribution
    PEP      $-308.85

Month: 2025-08 (Total Loss: $-45.77)
 Symbol  Contribution
   BIIB       $-45.77

Month: 2026-02 (Total Loss: $-652.12)
 Symbol  Contribution
    EXC      $-720.62
   CHTR      $-578.61
   MDLZ       $-60.75

Month: 2026-05 (Total Loss: $-4,097.37)
 Symbol  Contribution
     ZS    $-3,109.29
   TTWO    $-1,263.77

Month: 2026-06 (Total Loss: $-208.55)
 Symbol  Contribution
    KDP      $-714.12

Month: 2026-07 (Total Loss: $-1,036.85)
 Symbol  Contribution
    TRI      $-529.82
   VRSK      $-298.26
   CTAS      $-208.77
```

## Top 15 Largest Wins (Sorted by % Profit)

```text
Symbol       Date   Ex. date % Profit     Profit # bars
   ARM 2026-04-12 2026-06-21  138.39% $16,384.23     70
  KLAC 2025-06-08 2026-02-01   70.22%  $7,761.87    238
   AMD 2023-11-05 2024-03-17   55.95%  $5,351.07    133
   CEG 2024-02-11 2024-06-02   53.65%  $6,010.11    111
  QCOM 2023-11-19 2024-07-14   48.77%  $4,765.06    237
  AMAT 2023-11-26 2024-07-14   44.37%  $4,392.18    230
  FTNT 2024-09-01 2025-03-02   29.70%  $3,389.85    182
   ADI 2025-11-30 2026-03-01   21.96%  $2,445.11     91
  PANW 2023-02-26 2023-07-30   20.45%  $1,950.06    153
   ROP 2022-12-04 2024-04-14   18.88%  $1,888.17    496
  CSCO 2024-08-25 2025-03-09   18.15%  $2,089.33    196
  AMZN 2023-11-19 2024-04-21   17.32%  $1,692.54    153
  SHOP 2023-11-19 2024-02-11   14.37%  $1,403.81     84
  MSTR 2023-11-05 2024-01-07   12.93%  $1,236.22     63
  FAST 2025-05-18 2025-10-05   11.69%  $1,294.88    140
```

## Top 15 Largest Losses (Sorted by % Profit)

```text
Symbol       Date   Ex. date % Profit     Profit # bars
    ZS 2026-05-24 2026-05-31  -23.26% $-3,109.29      7
  PLTR 2023-02-19 2023-03-12  -19.22% $-1,837.01     21
  INTC 2025-02-16 2025-03-09  -17.82% $-2,115.21     21
  MRVL 2024-05-26 2024-07-21  -17.38% $-2,092.77     56
   ARM 2025-01-26 2025-03-02  -15.72% $-1,812.00     35
  TSLA 2025-05-18 2025-06-08  -15.06% $-1,668.15     21
  INTC 2023-04-02 2023-05-14  -12.36% $-1,165.89     42
  ISRG 2022-12-04 2023-02-19  -12.35% $-1,234.87     77
  CSGP 2024-12-01 2024-12-15  -12.10% $-1,456.51     14
  MSTR 2023-07-09 2023-08-13  -11.00% $-1,108.36     35
  CDNS 2025-05-18 2025-06-01  -10.13% $-1,122.81     14
  CSGP 2024-03-17 2024-04-14  -10.03% $-1,192.44     28
  TTWO 2026-05-17 2026-06-07   -9.69% $-1,263.77     21
  VRTX 2022-12-04 2022-12-18   -9.67%   $-966.62     14
   LIN 2022-12-04 2023-01-01   -9.54%   $-953.56     28
```

## Top 15 Largest Wins (Sorted by $ Amount)

```text
Symbol       Date   Ex. date % Profit     Profit # bars
   ARM 2026-04-12 2026-06-21  138.39% $16,384.23     70
  KLAC 2025-06-08 2026-02-01   70.22%  $7,761.87    238
   CEG 2024-02-11 2024-06-02   53.65%  $6,010.11    111
   AMD 2023-11-05 2024-03-17   55.95%  $5,351.07    133
  QCOM 2023-11-19 2024-07-14   48.77%  $4,765.06    237
  AMAT 2023-11-26 2024-07-14   44.37%  $4,392.18    230
  FTNT 2024-09-01 2025-03-02   29.70%  $3,389.85    182
   ADI 2025-11-30 2026-03-01   21.96%  $2,445.11     91
  CSCO 2024-08-25 2025-03-09   18.15%  $2,089.33    196
  PANW 2023-02-26 2023-07-30   20.45%  $1,950.06    153
   ROP 2022-12-04 2024-04-14   18.88%  $1,888.17    496
  AMZN 2023-11-19 2024-04-21   17.32%  $1,692.54    153
  SHOP 2023-11-19 2024-02-11   14.37%  $1,403.81     84
  FAST 2025-05-18 2025-10-05   11.69%  $1,294.88    140
  MSTR 2023-11-05 2024-01-07   12.93%  $1,236.22     63
```

## Top 15 Largest Losses (Sorted by $ Amount)

```text
Symbol       Date   Ex. date % Profit     Profit # bars
    ZS 2026-05-24 2026-05-31  -23.26% $-3,109.29      7
  INTC 2025-02-16 2025-03-09  -17.82% $-2,115.21     21
  MRVL 2024-05-26 2024-07-21  -17.38% $-2,092.77     56
  PLTR 2023-02-19 2023-03-12  -19.22% $-1,837.01     21
   ARM 2025-01-26 2025-03-02  -15.72% $-1,812.00     35
  TSLA 2025-05-18 2025-06-08  -15.06% $-1,668.15     21
  CSGP 2024-12-01 2024-12-15  -12.10% $-1,456.51     14
  TTWO 2026-05-17 2026-06-07   -9.69% $-1,263.77     21
  ISRG 2022-12-04 2023-02-19  -12.35% $-1,234.87     77
  CSGP 2024-03-17 2024-04-14  -10.03% $-1,192.44     28
  INTC 2023-04-02 2023-05-14  -12.36% $-1,165.89     42
  CDNS 2025-05-18 2025-06-01  -10.13% $-1,122.81     14
  MSTR 2023-07-09 2023-08-13  -11.00% $-1,108.36     35
  WDAY 2024-09-01 2024-10-27   -8.90% $-1,015.71     56
   TTD 2024-05-19 2024-07-28   -8.08%   $-995.31     70
```

## Trade Duration Histogram

![Trade Duration Histogram](images/trade_duration_histogram_2.png)

## Profit % vs. Duration Scatter Plot

![Profit % vs. Duration Scatter Plot](images/profit_vs_duration_scatter_plot_3.png)

## Average Trade Duration Summary (# bars)

```text
Average bars held for Wins: 124.00
Average bars held for Losses: 38.59
```

## MAE/MFE Analysis Plot

![MAE/MFE Analysis Plot](images/mae_mfe_analysis_plot_4.png)

## Average MAE/MFE Summary

```text
Average MAE for Losses: -10.01%
Average MFE for Wins: 38.65%
```

## Profit Distribution Plot

![Profit Distribution Plot](images/profit_distribution_plot_5.png)

## Profit Distribution Stats (% Profit)

```text
Skewness of % Profit: 3.54
Kurtosis of % Profit: 17.31
```

## Risk Profile — R-Multiple Distribution

![Risk Profile — R-Multiple Distribution](images/risk_profile_r-multiple_distribution_6.png)

## Strategy Equity vs SPY

![Strategy Equity vs SPY](images/strategy_equity_vs_spy_7.png)

## Equity Curve and Drawdown Plot

![Equity Curve and Drawdown Plot](images/equity_curve_and_drawdown_plot_8.png)

## Underwater Plot (Drawdown & Duration)

![Underwater Plot (Drawdown & Duration)](images/underwater_plot_drawdown_duration_9.png)

## Rolling 50-Trade Metrics

![Rolling 50-Trade Metrics](images/rolling_50-trade_metrics_10.png)

## Monte Carlo Percentile Statistics

```text
Final Equity Annual Return % Max. Drawdown $ Max. Drawdown % Lowest Eq.
1%       $82,286          -3.82%        $-27,388         -24.91%    $77,368
5%       $94,051          -1.22%        $-21,690         -19.65%    $83,521
10%     $101,331           0.26%        $-18,534         -16.77%    $87,397
25%     $111,987           2.29%        $-14,231         -12.27%    $92,208
50%     $125,503           4.65%        $-10,727          -9.13%    $96,324
75%     $142,009           7.26%         $-8,091          -6.86%    $98,805
90%     $158,529           9.65%         $-6,499          -5.28%   $100,000
95%     $167,013          10.80%         $-5,733          -4.52%   $100,000
99%     $184,127          12.98%         $-4,707          -3.39%   $100,000
```

## Monte Carlo Simulation Summary

```text
Based on 1000 simulation paths.
----------------------------------------
Final Equity:
  Average:            $128,071.33
  1st Percentile:     $82,286.38
  5th Percentile:     $94,051.36
  10th Percentile:    $101,330.63
  25th Percentile:    $111,986.82
  50th Percentile:    $125,502.82
  75th Percentile:    $142,009.34
  90th Percentile:    $158,529.48
  95th Percentile:    $167,012.72
  99th Percentile:    $184,127.11
  Probability Profit   90.80%

CAGR:
  Average:            4.81%
  1st Percentile:     -3.82%
  5th Percentile:     -1.22%
  10th Percentile:    0.26%
  25th Percentile:    2.29%
  50th Percentile:    4.65%
  75th Percentile:    7.26%
  90th Percentile:    9.65%
  95th Percentile:    10.80%
  99th Percentile:    12.98%

Maximum Drawdown ($):
  Average:            $-11,748.62
  1st Percentile:     $-27,388.30
  5th Percentile:     $-21,689.68
  10th Percentile:    $-18,534.49
  25th Percentile:    $-14,230.90
  50th Percentile:    $-10,727.34
  75th Percentile:    $-8,091.34
  90th Percentile:    $-6,499.06
  95th Percentile:    $-5,732.91
  99th Percentile:    $-4,707.32

Maximum Drawdown (%):
  Average:            -10.17%
  1st Percentile:     -24.91%
  5th Percentile:     -19.65%
  10th Percentile:    -16.77%
  25th Percentile:    -12.27%
  50th Percentile:    -9.13%
  75th Percentile:    -6.86%
  90th Percentile:    -5.28%
  95th Percentile:    -4.52%
  99th Percentile:    -3.39%

Lowest Equity Reached:
  Average:            $94,677.15
  1st Percentile:     $77,367.50
  5th Percentile:     $83,521.41
  10th Percentile:    $87,396.85
  25th Percentile:    $92,207.88
  50th Percentile:    $96,324.04
  75th Percentile:    $98,805.39
  90th Percentile:    $100,000.00
  95th Percentile:    $100,000.00
  99th Percentile:    $100,000.00
```

## MC Simulated Equity Paths

![MC Simulated Equity Paths](images/mc_simulated_equity_paths_11.png)

## MC Max Drawdown % Distribution

![MC Max Drawdown % Distribution](images/mc_max_drawdown_distribution_12.png)

## MC Lowest Equity Distribution

![MC Lowest Equity Distribution](images/mc_lowest_equity_distribution_13.png)

## MC Final Equity Distribution

![MC Final Equity Distribution](images/mc_final_equity_distribution_14.png)

## MC CAGR Distribution

![MC CAGR Distribution](images/mc_cagr_distribution_15.png)