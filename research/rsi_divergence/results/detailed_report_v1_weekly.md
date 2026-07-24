# Rsi Divergence 14 W  2.0X Atr14 Sl
---

## Data Cleaning Summary

```text
Initial trades loaded: 290
Rows dropped due to NaN in critical columns (Profit, % Profit, Date, Ex. date): 0
NaN Counts per Critical Column:
Profit      0
% Profit    0
Date        0
Ex. date    0

Sample of Dropped/Problematic Rows (if any):
None (No rows dropped)

Final Trade Count for Analysis: 290
```

## Overall Performance Metrics

```text
Total Net Profit:                             $13,791.53
Total Trades:                                 290
Total Shares Purchased:                       17,194
Strategy Total Return:                        13.79%

Gross Profit:                                 $158,106.00
Gross Loss:                                   $-144,314.47
Profit Factor:                                1.10

Win Rate:                                     35.52%
Average Winning Trade:                        $1,535.01
Average Losing Trade:                         $-771.74
Average Trade Profit:                         $47.56
Ratio Avg Win / Avg Loss:                     1.99

Max Consecutive Wins:                         7
Max Consecutive Losses:                       12

Expectancy per Trade:                         $47.56

Total Duration:                               5.00 years (1827 days)
Average Trades per Year:                      58.0
CAGR:                                         2.62%
Estimated After-Tax CAGR (30% tax):           1.86%
Annual Turnover:                              422.83%

Sharpe Ratio (Ann., Portfolio Daily, Rf=5.0%): 0.01
Sortino Ratio (Ann., Portfolio Daily, Rf=5.0%): 0.01
Calmar Ratio (CAGR / Max Equity DD%):         0.07
Max Equity Drawdown:                          36.85%

Sharpe (Per Trade, Arith Ret, Non-Ann, Rf=0%): 0.06
Sharpe (Per Trade, Log Ret, Non-Ann, Rf=0%):  -0.03

Tail Risk Analysis (Based on Trade Profit $):
--------------------------------------------------
95% Value at Risk (VaR):                      $-1,625.66
95% Conditional VaR (CVaR):                   $-2,009.37
99% Value at Risk (VaR):                      $-2,157.92
99% Conditional VaR (CVaR):                   $-2,386.11

Benchmark Comparison (SPY):
--------------------------------------------------
SPY Buy & Hold Return (period):               N/A
Beta vs SPY:                                  N/A
Alpha vs SPY (Ann., Rf=5.0%):                 N/A
```

## Walk-Forward Analysis (WFA)

```text
Split Ratio   : 80% In-Sample / 20% Out-of-Sample
IS/OOS Boundary : 2025-08-08

OOS P&L (% of capital):                       +39.92%
WFA Verdict:                                  Pass

Result: Out-of-Sample performance is consistent with In-Sample. No overfitting signal detected.
```

## Strategy Verdict

```text
No strategy verdict available — llm_verdict.json not found or no matching entry.
```

## Detailed Drawdown Analysis

```text
Max System Drawdown (Based on Equity %):      -36.85%

Drawdown Duration & Recovery Periods (Based on Cumulative Profit Peaks/Troughs):
---------------------------------------------------------------------------
Average Drawdown Duration (Trades):           72.0
Maximum Drawdown Duration (Trades):           163
Average Drawdown Duration (Days):             423
Maximum Drawdown Duration (Days):             853

Average Recovery Time (Trades):               43.3
Maximum Recovery Time (Trades):               77
Average Recovery Time (Days):                 312
Maximum Recovery Time (Days):                 469

Definitions:
 - Duration: Time from equity peak to new equity peak.
 - Recovery Time: Time from drawdown trough to new equity peak.


Top 5 Largest Drawdown Periods (by $ Amount, based on Cum. Profit Peaks):
------------------------------------------------------------------------------------------
Start Date   Trough Date  End Date     Duration(d)   DD Amount($)    Peak Val($)    
------------------------------------------------------------------------------------
2021-11-28   2022-12-18   2024-03-31   853           37,109.42       38.93          
2024-04-07   2025-04-06   2026-07-19   833           34,080.22       5,283.51       
2026-07-19   2026-07-19   Ongoing      0             1,655.63        14,700.89      
2024-03-31   2024-04-07   2024-04-07   7             761.45          947.06
```

## Performance per Symbol Analysis

```text
Performance per Symbol (Sorted by Win Rate):
================================================================================
       Total_Trades Total_Profit Win_Rate Avg_Profit   Avg_Loss Profit_Factor Avg_Pct_Return Avg_Bars_Held
Symbol                                                                                                    
CTAS              1      $174.59   100.0%    $174.59      $0.00           inf         10.41%          14.0
DASH              2    $2,910.87   100.0%  $1,455.44      $0.00           inf         13.96%          63.0
CTSH              2    $1,262.86   100.0%    $631.43      $0.00           inf          8.92%         108.0
CSCO              3    $1,662.38    66.7%  $1,121.81   $-581.24          3.86         15.92%         112.0
CSX               5      $667.08    60.0%    $553.32   $-496.45          1.67          2.93%         130.2
CEG               2       $79.57    50.0%     $93.25    $-13.68          6.82          4.01%          38.5
COST              4    $4,779.96    50.0%  $2,511.58   $-121.60         20.65         11.38%         143.2
CCEP             10      $264.66    50.0%    $652.55   $-599.62          1.09          3.54%          92.3
AZN              10    $2,873.91    50.0%  $1,273.65   $-698.87          1.82          3.42%          70.5
AMGN              2      $222.23    50.0%    $418.95   $-196.71          2.13          0.91%          35.0
PCAR              2      $551.65    50.0%  $1,388.79   $-837.14          1.66          2.85%          56.0
ADP              13    $2,277.22    46.2%    $870.25   $-420.61          1.77          1.69%          71.5
AEP              11      $401.43    45.5%    $681.62   $-501.11          1.13          0.17%          65.3
ARM               7   $-4,099.56    42.9%    $886.06 $-1,689.43          0.39         20.09%          71.7
CDNS              7    $1,209.43    42.9%  $1,532.85   $-847.28          1.36          1.98%          79.7
ADI              12    $3,717.44    41.7%  $1,648.61   $-646.52          1.82          4.60%          65.2
AXON              5    $2,026.53    40.0%  $2,165.58   $-768.21          1.88          8.14%          71.2
ADSK             13   $-3,077.16    38.5%  $1,161.30 $-1,110.46          0.65         -2.70%          83.8
BIIB             16   $-3,448.90    37.5%    $994.51   $-941.59          0.63         -2.02%          60.7
AAPL             22    $2,384.33    36.4%  $1,441.89   $-653.63          1.26          1.42%          63.8
BKNG             14   $-4,486.79    35.7%    $479.28   $-764.80          0.35          0.15%          69.9
ABNB              3   $-3,144.68    33.3%    $392.23 $-1,768.45          0.11        -14.38%          58.3
CSGP              3     $-658.79    33.3%    $262.60   $-460.69          0.29         -3.06%          86.0
META              3   $-2,067.16    33.3%     $38.93 $-1,053.05          0.02         -7.04%          23.3
AMZN              6    $2,771.03    33.3%  $1,678.45   $-146.47          5.73          3.81%          89.5
ASML              6    $1,113.92    33.3%  $1,990.90   $-716.97          1.39          2.89%          97.8
AMAT             19    $2,060.93    31.6%  $2,994.39 $-1,223.49          1.13          2.67%          67.6
CHTR             10      $904.50    30.0%  $1,101.99   $-343.06          1.38         -2.96%          63.6
AMD              18   $22,798.62    27.8%  $8,593.25 $-1,551.36          2.13         16.42%          82.7
ADBE             15   $-6,051.97    26.7%  $1,322.06 $-1,030.93          0.47         -3.92%          57.3
DDOG              4   $-3,008.19    25.0%    $174.30 $-1,060.83          0.05         -6.86%          66.5
CPRT              7   $-1,752.30    14.3%      $2.64   $-292.49          0.00         -5.62%          31.0
CMCSA             8   $-1,722.35    12.5%    $255.27   $-282.52          0.13         -7.65%          46.2
CDW              17   $-5,153.54    11.8%    $570.93   $-419.69          0.18         -5.62%          41.9
EA                2     $-811.64     0.0%      $0.00   $-405.82          0.00         -8.58%          10.5
FANG              1      $-14.85     0.0%      $0.00    $-14.85          0.00         -1.03%          49.0
HON               1     $-347.56     0.0%      $0.00   $-347.56          0.00         -5.15%         104.0
LRCX              1      $-87.85     0.0%      $0.00    $-87.85          0.00         -0.85%          63.0
SBUX              1     $-741.60     0.0%      $0.00   $-741.60          0.00         -7.36%          49.0
SHOP              2   $-2,648.75     0.0%      $0.00 $-1,324.38          0.00        -13.30%          31.5

Symbols with Profit Factor < 1.00 (Sorted by PF):
================================================================================
       Total_Trades Total_Profit Win_Rate Profit_Factor
Symbol                                                 
SHOP              2   $-2,648.75     0.0%          0.00
LRCX              1      $-87.85     0.0%          0.00
HON               1     $-347.56     0.0%          0.00
FANG              1      $-14.85     0.0%          0.00
EA                2     $-811.64     0.0%          0.00
SBUX              1     $-741.60     0.0%          0.00
CPRT              7   $-1,752.30    14.3%          0.00
META              3   $-2,067.16    33.3%          0.02
DDOG              4   $-3,008.19    25.0%          0.05
ABNB              3   $-3,144.68    33.3%          0.11
CMCSA             8   $-1,722.35    12.5%          0.13
CDW              17   $-5,153.54    11.8%          0.18
CSGP              3     $-658.79    33.3%          0.29
BKNG             14   $-4,486.79    35.7%          0.35
ARM               7   $-4,099.56    42.9%          0.39
ADBE             15   $-6,051.97    26.7%          0.47
BIIB             16   $-3,448.90    37.5%          0.63
ADSK             13   $-3,077.16    38.5%          0.65
```

## Profitable vs. Unprofitable Symbol Comparison

```text
Comparison based on PF >= 1.50 vs PF < 1.00

Profitable Symbols (15 symbols, 87 trades):
  Avg % Profit per Trade: 7.47%
  Avg Bars Held: 80.15
  Overall Win Rate: 45.98%

Unprofitable Symbols (18 symbols, 118 trades):
  Avg % Profit per Trade: -2.87%
  Avg Bars Held: 57.77
  Overall Win Rate: 26.27%

Interpretation Notes:
- Compare Avg Bars Held, Avg % Profit, Win Rate between groups.
```

## Monthly Net Profit Plot

![Monthly Net Profit Plot](images/monthly_net_profit_plot_1.png)

## Top 5 Losing Symbol Contributors During Losing Months

```text
Month: 2021-10 (Total Loss: $-2,077.10)
 Symbol  Contribution
   CPRT    $-1,022.21
   PCAR      $-837.14
   SHOP      $-630.16

Month: 2021-11 (Total Loss: $-3,901.74)
 Symbol  Contribution
   SHOP    $-2,018.59
   META    $-1,053.70
   SBUX      $-741.60
   LRCX       $-87.85

Month: 2021-12 (Total Loss: $-1,663.98)
 Symbol  Contribution
   ADSK    $-1,248.49
   META    $-1,052.39
   CPRT      $-356.59
    AEP      $-198.58
   AMGN      $-196.71

Month: 2022-01 (Total Loss: $-7,390.04)
 Symbol  Contribution
   AMAT    $-2,766.06
   AXON    $-1,978.12
   ADSK    $-1,475.73
   CHTR      $-870.28
   CCEP      $-846.39

Month: 2022-02 (Total Loss: $-3,405.84)
 Symbol  Contribution
   BKNG    $-2,417.01
   CCEP    $-1,620.71
  CMCSA      $-487.10
   CPRT       $-95.39

Month: 2022-03 (Total Loss: $-1,610.93)
 Symbol  Contribution
   ADSK    $-1,491.41
    HON      $-347.56
   BKNG       $-75.84

Month: 2022-04 (Total Loss: $-3,742.30)
 Symbol  Contribution
   ABNB    $-1,839.29
   ADBE    $-1,068.82
    ADI      $-447.49
    ADP      $-386.69

Month: 2022-05 (Total Loss: $-3,037.62)
 Symbol  Contribution
   ABNB    $-1,697.61
   AMAT    $-1,237.34
   AMZN      $-102.67

Month: 2022-08 (Total Loss: $-3,876.07)
 Symbol  Contribution
   ADBE    $-1,094.75
   ASML    $-1,011.24
    ADI      $-972.36
   AAPL      $-797.72

Month: 2022-09 (Total Loss: $-2,750.24)
 Symbol  Contribution
    AMD    $-1,482.92
   ADSK      $-909.26
    ADP      $-725.76
   AAPL      $-662.89
   ADBE      $-615.95

Month: 2022-11 (Total Loss: $-373.90)
 Symbol  Contribution
   AAPL      $-373.90

Month: 2023-06 (Total Loss: $-1,775.28)
 Symbol  Contribution
    AMD    $-1,372.12
   BIIB      $-331.41
   CPRT       $-71.75

Month: 2023-08 (Total Loss: $-326.96)
 Symbol  Contribution
    AEP      $-981.03
   AAPL      $-441.83
   DDOG      $-339.68
   CPRT       $-23.05

Month: 2023-12 (Total Loss: $-476.34)
 Symbol  Contribution
   AAPL      $-476.34

Month: 2024-02 (Total Loss: $-761.45)
 Symbol  Contribution
   AAPL      $-761.45

Month: 2024-03 (Total Loss: $-912.75)
 Symbol  Contribution
    AMD    $-1,974.36
   BIIB    $-1,208.76
    ADP      $-346.43
    CDW      $-199.34
   AMZN       $-10.66

Month: 2024-05 (Total Loss: $-20.19)
 Symbol  Contribution
    CDW       $-20.19

Month: 2024-07 (Total Loss: $-7,573.97)
 Symbol  Contribution
   AMAT    $-3,165.70
    AMD    $-2,857.96
   BIIB    $-1,346.09
   COST      $-204.22

Month: 2024-09 (Total Loss: $-2,841.75)
 Symbol  Contribution
    AZN    $-1,262.24
    CDW    $-1,046.58
   BIIB    $-1,008.88

Month: 2024-11 (Total Loss: $-7,353.28)
 Symbol  Contribution
    AMD    $-2,153.27
   AMAT    $-1,788.07
   BIIB    $-1,336.87
   ADSK    $-1,074.91
   CSGP      $-473.49

Month: 2024-12 (Total Loss: $-3,916.64)
 Symbol  Contribution
   DDOG    $-1,577.51
   BIIB    $-1,290.12
    CSX      $-467.13
   AMAT      $-378.98
   ADSK      $-202.90

Month: 2025-01 (Total Loss: $-3,958.25)
 Symbol  Contribution
    AMD    $-2,195.55
   AAPL      $-868.70
     EA      $-811.64
    ARM      $-587.49

Month: 2025-02 (Total Loss: $-7,542.57)
 Symbol  Contribution
    AMD    $-1,988.32
   AMAT    $-1,665.06
   ASML    $-1,478.59
   DDOG    $-1,265.29
   BIIB      $-633.42

Month: 2025-03 (Total Loss: $-9,507.34)
 Symbol  Contribution
   AAPL    $-2,382.60
    CDW    $-2,017.15
    ADI    $-1,908.61
    AMD    $-1,370.66
   BIIB      $-994.53

Month: 2025-07 (Total Loss: $-278.28)
 Symbol  Contribution
   AXON      $-196.04
   ASML       $-82.24

Month: 2025-09 (Total Loss: $-947.82)
 Symbol  Contribution
   ADBE    $-1,181.12
  CMCSA      $-371.45
   COST       $-38.98

Month: 2025-10 (Total Loss: $-593.20)
 Symbol  Contribution
   BKNG      $-864.38
   CDNS      $-781.95
    CDW      $-112.76

Month: 2025-11 (Total Loss: $-5,622.44)
 Symbol  Contribution
    ARM    $-2,337.58
    AMD    $-1,368.31
    CDW      $-684.43
   CDNS      $-665.38
   ADBE      $-573.24

Month: 2026-01 (Total Loss: $-2,793.37)
 Symbol  Contribution
   ADBE    $-2,565.11
   AAPL      $-757.34
   CPRT      $-185.94
   BIIB       $-52.35

Month: 2026-02 (Total Loss: $-3,744.29)
 Symbol  Contribution
   BKNG    $-2,427.88
    AMD    $-1,993.49
   ADBE    $-1,034.08

Month: 2026-04 (Total Loss: $-103.80)
 Symbol  Contribution
   CHTR      $-103.80

Month: 2026-06 (Total Loss: $-529.74)
 Symbol  Contribution
   ADBE      $-707.77
    ADI      $-182.49

Month: 2026-07 (Total Loss: $-3,183.37)
 Symbol  Contribution
    ARM    $-1,207.46
   AMAT    $-1,196.45
   CDNS    $-1,088.01
```

## Top 15 Largest Wins (Sorted by % Profit)

```text
Symbol       Date   Ex. date % Profit     Profit # bars
   ARM 2026-01-04 2026-06-21  192.70%    $640.94    167
   AMD 2026-03-01 2026-07-19  179.61% $17,142.17    139
   AMD 2025-04-06 2025-11-16  169.22% $12,349.16    224
  AMAT 2025-08-31 2026-03-01  106.42%  $9,774.11    182
   AMD 2022-10-09 2023-06-25   86.78%  $5,669.00    259
   AMD 2023-09-24 2024-03-17   83.01%  $7,647.15    175
  AMAT 2026-03-08 2026-07-05   65.17%  $5,863.83    118
  ASML 2022-10-09 2023-08-06   53.94%  $3,524.05    301
   ADI 2025-04-06 2025-09-21   50.34%  $3,673.84    168
  AMZN 2023-01-01 2023-09-24   45.84%  $3,355.43    265
  BKNG 2022-10-09 2023-05-28   45.21%    $669.88    231
  AAPL 2025-04-06 2026-01-04   44.26%  $3,229.69    273
  ADBE 2023-02-19 2023-09-24   43.43%  $3,114.54    216
  COST 2023-02-26 2024-03-31   43.11%  $3,503.48    398
  CDNS 2023-01-08 2023-08-13   39.29%  $3,072.87    216
```

## Top 15 Largest Losses (Sorted by % Profit)

```text
Symbol       Date   Ex. date % Profit     Profit # bars
   ARM 2025-03-02 2025-03-30  -28.78% $-2,625.19     27
   AMD 2022-09-04 2022-10-09  -28.58% $-1,482.92     35
  ABNB 2022-05-08 2022-06-12  -26.36% $-1,697.61     35
   ARM 2025-11-09 2025-12-14  -25.03% $-2,337.58     35
   AMD 2025-01-05 2025-02-23  -22.76% $-2,195.55     49
  ABNB 2022-04-17 2022-05-08  -22.21% $-1,839.29     21
  CHTR 2026-04-26 2026-05-17  -21.83%    $-57.06     21
   AMD 2025-02-23 2025-03-30  -21.08% $-1,988.32     34
   AMD 2024-11-10 2025-01-05  -20.90% $-2,153.27     56
  SHOP 2021-11-28 2022-01-02  -20.30% $-2,018.59     35
   AMD 2026-02-01 2026-03-01  -20.24% $-1,993.49     28
  AXON 2022-01-09 2022-04-24  -20.14% $-1,978.12    104
  ASML 2022-08-28 2022-10-09  -19.84% $-1,011.24     42
   AMD 2025-03-30 2025-04-06  -18.72% $-1,370.66      7
   AMD 2024-07-14 2024-07-21  -18.20% $-2,027.34      7
```

## Top 15 Largest Wins (Sorted by $ Amount)

```text
Symbol       Date   Ex. date % Profit     Profit # bars
   AMD 2026-03-01 2026-07-19  179.61% $17,142.17    139
   AMD 2025-04-06 2025-11-16  169.22% $12,349.16    224
  AMAT 2025-08-31 2026-03-01  106.42%  $9,774.11    182
   AMD 2023-09-24 2024-03-17   83.01%  $7,647.15    175
  AMAT 2026-03-08 2026-07-05   65.17%  $5,863.83    118
   AMD 2022-10-09 2023-06-25   86.78%  $5,669.00    259
   ADI 2025-04-06 2025-09-21   50.34%  $3,673.84    168
  ASML 2022-10-09 2023-08-06   53.94%  $3,524.05    301
  COST 2023-02-26 2024-03-31   43.11%  $3,503.48    398
  AMZN 2023-01-01 2023-09-24   45.84%  $3,355.43    265
  AAPL 2025-04-06 2026-01-04   44.26%  $3,229.69    273
  ADBE 2023-02-19 2023-09-24   43.43%  $3,114.54    216
  CDNS 2023-01-08 2023-08-13   39.29%  $3,072.87    216
  ADSK 2024-08-04 2024-11-24   28.39%  $3,022.36    112
  DASH 2024-10-20 2025-02-23   26.18%  $2,776.91    126
```

## Top 15 Largest Losses (Sorted by $ Amount)

```text
Symbol       Date   Ex. date % Profit     Profit # bars
   ARM 2025-03-02 2025-03-30  -28.78% $-2,625.19     27
   ARM 2025-11-09 2025-12-14  -25.03% $-2,337.58     35
   AMD 2025-01-05 2025-02-23  -22.76% $-2,195.55     49
   AMD 2024-11-10 2025-01-05  -20.90% $-2,153.27     56
   AMD 2024-07-14 2024-07-21  -18.20% $-2,027.34      7
  SHOP 2021-11-28 2022-01-02  -20.30% $-2,018.59     35
   AMD 2026-02-01 2026-03-01  -20.24% $-1,993.49     28
   AMD 2025-02-23 2025-03-30  -21.08% $-1,988.32     34
  AXON 2022-01-09 2022-04-24  -20.14% $-1,978.12    104
   AMD 2024-03-17 2024-04-14  -18.15% $-1,974.36     28
  AMAT 2024-07-21 2024-08-04  -17.17% $-1,858.67     14
  ABNB 2022-04-17 2022-05-08  -22.21% $-1,839.29     21
  AMAT 2024-11-10 2024-12-15  -17.35% $-1,788.07     35
  ABNB 2022-05-08 2022-06-12  -26.36% $-1,697.61     35
  AMAT 2025-02-23 2025-03-30  -17.65% $-1,665.06     34
```

## Trade Duration Histogram

![Trade Duration Histogram](images/trade_duration_histogram_2.png)

## Profit % vs. Duration Scatter Plot

![Profit % vs. Duration Scatter Plot](images/profit_vs_duration_scatter_plot_3.png)

## Average Trade Duration Summary (# bars)

```text
Average bars held for Wins: 127.68
Average bars held for Losses: 36.09
```

## MAE/MFE Analysis Plot

![MAE/MFE Analysis Plot](images/mae_mfe_analysis_plot_4.png)

## Average MAE/MFE Summary

```text
Average MAE for Losses: -14.32%
Average MFE for Wins: 39.47%
```

## Profit Distribution Plot

![Profit Distribution Plot](images/profit_distribution_plot_5.png)

## Profit Distribution Stats (% Profit)

```text
Skewness of % Profit: 4.24
Kurtosis of % Profit: 24.91
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
1%       $50,421         -12.79%        $-63,896         -58.86%    $42,123
5%       $63,783          -8.60%        $-51,883         -47.86%    $55,772
10%      $73,744          -5.91%        $-46,360         -41.54%    $61,904
25%      $89,657          -2.16%        $-36,243         -32.00%    $75,169
50%     $110,816           2.07%        $-27,341         -23.18%    $85,363
75%     $131,215           5.58%        $-20,708         -17.30%    $93,295
90%     $154,537           9.09%        $-16,216         -13.12%    $97,664
95%     $166,895          10.78%        $-14,517         -11.10%    $99,028
99%     $190,195          13.71%        $-11,502          -9.10%   $100,000
```

## Monte Carlo Simulation Summary

```text
Based on 1000 simulation paths.
----------------------------------------
Final Equity:
  Average:            $112,047.53
  1st Percentile:     $50,421.04
  5th Percentile:     $63,783.18
  10th Percentile:    $73,744.36
  25th Percentile:    $89,656.51
  50th Percentile:    $110,815.81
  75th Percentile:    $131,214.86
  90th Percentile:    $154,536.63
  95th Percentile:    $166,894.90
  99th Percentile:    $190,194.92
  Probability Profit   62.80%

CAGR:
  Average:            1.66%
  1st Percentile:     -12.79%
  5th Percentile:     -8.60%
  10th Percentile:    -5.91%
  25th Percentile:    -2.16%
  50th Percentile:    2.07%
  75th Percentile:    5.58%
  90th Percentile:    9.09%
  95th Percentile:    10.78%
  99th Percentile:    13.71%

Maximum Drawdown ($):
  Average:            $-29,589.74
  1st Percentile:     $-63,896.01
  5th Percentile:     $-51,882.85
  10th Percentile:    $-46,360.41
  25th Percentile:    $-36,242.63
  50th Percentile:    $-27,340.97
  75th Percentile:    $-20,708.50
  90th Percentile:    $-16,216.16
  95th Percentile:    $-14,517.35
  99th Percentile:    $-11,502.02

Maximum Drawdown (%):
  Average:            -25.63%
  1st Percentile:     -58.86%
  5th Percentile:     -47.86%
  10th Percentile:    -41.54%
  25th Percentile:    -32.00%
  50th Percentile:    -23.18%
  75th Percentile:    -17.30%
  90th Percentile:    -13.12%
  95th Percentile:    -11.10%
  99th Percentile:    -9.10%

Lowest Equity Reached:
  Average:            $82,321.22
  1st Percentile:     $42,122.95
  5th Percentile:     $55,771.67
  10th Percentile:    $61,904.47
  25th Percentile:    $75,169.35
  50th Percentile:    $85,363.31
  75th Percentile:    $93,294.50
  90th Percentile:    $97,664.00
  95th Percentile:    $99,028.18
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