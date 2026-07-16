"""
Research session context: ETF MA/EMA/SMA strategy scan + Triple EMA Crossover origin study.

═══════════════════════════════════════════════════════════════════════
SESSION ORIGIN — Triple EMA Crossover (2H Forex/Equity)
═══════════════════════════════════════════════════════════════════════

Starting point: a discretionary trader's X post claiming:
  - $2M+/year trading 3 EMAs on the 2H chart
  - 41% win rate, 1:3.2 R:R, ~7 trades/month
  - 2.5% risk per trade
  - Only A+ setups — highly selective

Math check: 0.41 × 3.2R − 0.59 × 1R = 0.712R EV/trade ✓ Elite edge.

BACKTEST SETUP (Triple EMA — 2H Polygon data, 2021-07-16 to 2026-07-15)
───────────────────────────────────────────────────────────────────────
  data_provider   : polygon
  timeframe       : H
  timeframe_multiplier : 2
  start_date      : 2009-01-01  (Polygon cap applied: actual 2021-07-19)
  rolling_sharpe_window : 630   (≈ 5 yr window on 2H bars)
  stop_loss_configs: [{"type": "none"}]
  wfa_split_ratio : 0.80

EMA PERIODS TESTED
  V1 (bare cross)  : (5/13/50), (8/21/55), (10/20/50)
  V2 (+ 200-bar TF): same 3 sets, " TF" suffix
  V3 (+ HTF + ATR + session): same 3 sets, " PRO" suffix
    - Daily HTF 50-EMA: close must be above daily 50-EMA (uptrend gate)
    - ATR expansion: 14-bar ATR > 50-bar rolling ATR mean
    - NYC session: 9:30–11am → 8am–12pm on 2H grid (even-hour bar boundary)

EQUITY RESULTS (5 US large-caps: AAPL, NVDA, MSFT, TSLA, AMZN — approx)
  Triple EMA (5/13/50) V1 : ~33% WR, +0.19R expectancy, WFA Pass ✓
  All V1/V2 period sets   : WFA Pass, positive expectancy on trending equities
  V3 (PRO) filters reduce losses and max DD significantly

FOREX RESULTS (7 majors: EUR/USD, GBP/USD, USD/JPY, AUD/USD, USD/CAD,
               NZD/USD, GBP/JPY)
  All pairs, all filter variants: 14–28% WR, negative expectancy
  USD/JPY: only pair that went positive under any filter → WFA "Likely Overfitted"
           driven by 2021–2024 yen devaluation macro regime, not strategy edge

CONCLUSION (Triple EMA)
  Mechanical signal has genuine alpha on trending equities.
  FX majors at 2H are too mean-reverting for this momentum approach.
  Filters (trend, vol, session) directionally correct but insufficient alone.
  The trader's edge lives in his discretionary A+ selection layer
  (selecting ~1-in-3 mechanical signals = the 8pp WR gap from 33% → 41%).

CODE: custom_strategies/triple_ema_crossover.py (committed on this branch)

═══════════════════════════════════════════════════════════════════════
ETF MA/EMA/SMA STRATEGY SCAN
═══════════════════════════════════════════════════════════════════════

QUESTION: Is there durable alpha in any variation of MA/SMA/EMA-based
          longer-term strategies when applied to a broad ETF universe?

UNIVERSE (23 ETFs — tickers_to_scan/etfs_ma_research.json)
  Broad market : SPY, QQQ, IWM, DIA, MDY
  Sectors      : XLK, XLF, XLE, XLV, XLI, XLY, XLP, XLU, XLB
  Bonds        : TLT, IEF
  Commodities  : GLD, USO
  International: EFA, EEM
  Factor       : MTUM, VTV, VUG

BACKTEST SETUP (ETF scan)
───────────────────────────────────────────────────────────────────────
  data_provider        : polygon
  timeframe            : D
  timeframe_multiplier : 1
  start_date           : 2004-01-01 (Polygon cap: actual 2021-07-19)
  stop_loss_configs    : [{"type": "none"}]
  wfa_split_ratio      : 0.80   (IS: 2021-07-19–2025-07-15 | OOS: 2025-07-15–2026-07-15)
  strategies           : "all"  (81 strategies registered, 80 valid = 1863 tasks)
  Benchmarks           : SPY +77.61%, QQQ +102.37% (buy-and-hold, 2021–2026)

Run ID: etf-ma-research_2026-07-16_07-00-08

FULL RESULTS — MA/EMA/SMA FAMILY (sorted by P&L)
───────────────────────────────────────────────────────────────────────
  Strategy                              P&L%    vs SPY   Sharpe  Max DD   WFA
  ─────────────────────────────────────────────────────────────────────────────
  SMA Crossover (50d/200d)             +34.6%   -43.1%   0.15   18.3%   Pass
  MA Confluence w/ Regime Filter       +30.6%   -47.1%   0.10    8.3%   Pass  ← best risk-adj
  MA Confluence (Fast Entry & Exit)    +22.6%   -55.0%  -0.01   17.6%   Pass
  SMA 200 Trend Filter (200d)          +22.2%   -55.4%  -0.01   16.4%   Pass
  EMA Crossover w/ SPY+VIX Filter      +18.3%   -59.3%  -0.10   11.8%   Pass
  EMA Crossover (Unfiltered)           +15.9%   -61.7%  -0.09   20.5%   Pass
  EMA Crossover w/ SPY-Only Filter     +15.9%   -61.7%  -0.09   20.5%   Pass
  EMA Crossover w/ VIX-Only Filter     +15.9%   -61.7%  -0.09   20.5%   Pass
  MA Confluence (Fast Entry)           +12.7%   -64.9%  -0.15   19.3%   Pass
  Triple EMA (5/13/50)                 +10.9%   -66.7%  -0.18   18.7%   Pass
  Triple EMA (5/13/50) TF             + 9.7%   -67.9%  -0.23   19.0%   Pass
  MA Confluence (Full Stack)           + 9.4%   -68.2%  -0.21   23.1%   Pass
  Triple EMA (8/21/55)                 + 7.5%   -70.1%  -0.21   15.4%   Pass
  SMA Crossover (20d/50d)              + 7.4%   -70.2%  -0.23   21.2%   Pass
  MA Confluence (Fast MA Exit)         + 8.7%   -68.9%  -0.23   18.6%   Pass
  MA Bounce (20d)                      + 6.4%   -71.2%  -0.25   17.3%   Pass
  MA Confluence (Medium MA Exit)       + 2.9%   -74.7%  -0.45   15.0%   Pass
  Triple EMA (10/20/50)                + 0.7%   -76.9%  -0.33   19.7%   Pass

TOP NON-MA PERFORMERS ON SAME UNIVERSE (for comparison)
───────────────────────────────────────────────────────────────────────
  Bollinger Band Fade (20d/2.0)        +49.9%   -27.7%   0.35   10.7%   Pass  ← #1 overall
  Bollinger Band Fade (20d/2.5)        +43.4%   -34.2%   0.33    7.1%   Pass
  SPY/TLT Seasonal Rotation            +43.1%   -34.6%   0.24   24.0%   Pass
  Stochastic Oscillator (14d)          +40.4%   -37.2%   0.24   12.7%   Pass
  RSI Mean Reversion (14/30)           +39.6%   -38.1%   0.29   10.0%   Pass
  Williams %R (-80/-50)                +38.0%   -39.6%   0.21   13.3%   Pass
  Bollinger Mean Rev. w/ ATR Stop      +32.4%   -45.3%   0.12    7.7%   Pass

REGIME ANALYSIS (EMA Crossover Unfiltered — notable finding)
  Low VIX (<15)  : +8.9% — works in calm trending markets
  Mid VIX (15-25): +19.4% — best environment (moderate vol = good trending)
  High VIX (>25) : -0.1% — breaks in high-vol regimes

CORRELATION ALERTS (r > 0.70 within MA family)
  EMA Crossover variants (Unfiltered / SPY-only / VIX-only): r=1.00 → identical signals
  Triple EMA (V1 vs V2 same periods): r=0.94–0.95 → V2 TF filter barely differentiates
  MA Confluence Fast Entry & Exit ↔ Fast MA Exit: r=0.91

KEY CONCLUSIONS
───────────────────────────────────────────────────────────────────────
1. NO MA/EMA/SMA strategy beats ETF buy-and-hold during a strong bull run (2021–2026).
   This is expected — trend-following exits during pullbacks that eventually recover.

2. BEST MA STRATEGY: SMA Crossover (50d/200d) — golden cross — at +34.6%, Sharpe 0.15.
   Clean, WFA-validated, interpretable. Still -43% vs SPY B&H.

3. BEST RISK-ADJUSTED MA: MA Confluence w/ Regime Filter — +30.6%, only 8.3% max DD,
   Sharpe 0.10. The regime filter (VIX gate) dramatically reduces drawdown vs raw confluence.

4. MEAN REVERSION WINS ON ETFs IN BULL MARKETS: Bollinger Fade at 0.35 Sharpe cleanly
   dominates. ETFs mean-revert inside the bull trend more reliably than they trend further.

5. EMA FILTER FINDING: SPY-Only, VIX-Only, and Unfiltered EMA Crossover produce IDENTICAL
   signals on this ETF universe (r=1.00). The filters add no differentiation — ETFs are
   already highly correlated to SPY, making the SPY filter a no-op.

6. EMA REGIME SWEET SPOT: Mid-VIX (15–25) is where EMA crossover makes all its money.
   Low-VIX environments are profitable but smaller. High-VIX (>25) breaks the signal.

NEXT RESEARCH DIRECTIONS
───────────────────────────────────────────────────────────────────────
A. BEAR MARKET VALIDATION: This run only covers 2021–2026 (bull + high-vol 2022).
   Run on 2007–2012 period (if data available) to stress-test in sustained downtrend.
   The golden cross is specifically designed to sidestep bear markets — validate that claim.

B. MA CONFLUENCE + VIX REGIME FILTER: isolate the VIX gate's contribution. Run
   MA Confluence (Full Stack) vs MA Confluence w/ Regime Filter on 2022 bear only.

C. MA WITH STOPS: Re-run SMA Crossover (50d/200d) with a 5% and 8% percentage stop.
   config.py stop_loss_configs: [{"type":"percentage","value":0.05},{"type":"percentage","value":0.08}]
   Hypothesis: reducing drawdown from 18% to 10% might flip the risk-adjusted comparison.

D. WEEKLY TIMEFRAME TEST: MA strategies are inherently noisy on daily. Re-run on weekly
   bars (timeframe="W") to reduce whipsaw. Requires fewer trades but cleaner signals.

E. TRIPLE EMA ON DAILY ETFs — DEEPER STUDY: Triple EMA (5/13/50) posted +10.9% with
   WFA Pass. This is a short-term momentum signal on daily bars. Worth studying:
   - Does it beat MA Confluence on individual sector ETFs?
   - Is there regime dependency (only works in low/mid VIX)?

TO REPRODUCE
───────────────────────────────────────────────────────────────────────
  # ETF universe:
  "portfolios": {"ETF Universe — MA Research": "etfs_ma_research.json"}

  # Config snapshot used for this run:
  data_provider        = "polygon"
  timeframe            = "D"
  timeframe_multiplier = 1
  start_date           = "2004-01-01"   # Polygon returns 2021-07-19
  initial_capital      = 100000.0
  allocation_per_trade = 0.10
  stop_loss_configs    = [{"type": "none"}]
  wfa_split_ratio      = 0.80
  strategies           = "all"
  rolling_sharpe_window = 126

  # Run commands:
  source .venv/bin/activate
  python main.py --name "etf-ma-research"
  python main.py --name "etf-ma-research-verbose" --verbose
"""
