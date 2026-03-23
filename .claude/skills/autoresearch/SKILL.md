# Autoresearch: Strategy Iteration

## Goal
Improve the SMA Crossover trading strategy's total return by iterating on parameters, filters, and stop losses.

## Metric
Total return % (higher is better). Measured by: `python autoresearch_score.py`

## Scope — Files you CAN modify
- `custom_strategies/autoresearch_strategy.py` — the strategy logic
- `config.py` — ONLY the `strategies` list and stop_loss_configs section

## Scope — Files you MUST NOT modify
- `main.py` (except the autoresearch hook already added)
- `helpers/indicators.py` (use existing indicators only)
- `helpers/portfolio_simulations.py`
- `autoresearch_score.py`

## How to run a single iteration
1. Make ONE focused change to the strategy file
2. Git commit the change
3. Run: `$env:AUTORESEARCH = "1"; python main.py`
4. Run: `python autoresearch_score.py`
5. If SCORE improved → keep. If worse → `git revert HEAD --no-edit`
6. Log the result

## Available indicators (from helpers/indicators.py)
- `sma_crossover_logic(df, fast=20, slow=50)` — SMA crossover signals
- `rsi_logic(df)` — RSI signals
- `macd_crossover_logic(df)` — MACD crossover
- `bollinger_breakout_logic(df)` — Bollinger band breakout
- `roc_logic(df)` — Rate of change
- `stochastic_logic(df)` — Stochastic oscillator
- `ma_bounce_logic(df)` — Moving average bounce
- `ema_crossover_unfiltered_logic(df)` — EMA crossover

## Strategy file template
The strategy must use the `@register_strategy` decorator and set `df["Signal"]` to 1 (buy) or 0 (no position). See `custom_strategies/` for examples.

## Variables to experiment with
- SMA lookback periods (fast: 5-50, slow: 20-200)
- RSI filter (only enter when RSI < 30, or RSI > 50)
- VIX regime filter (only trade when VIX < 20)
- Stop loss type (none, percentage 2-10%, ATR-based)
- SPY trend filter (only trade when SPY > SMA200)
- Volume filter (only trade on high volume days)
- Combine multiple indicators

## Constraints
- Portfolio: SPY, QQQ, AAPL (keep small for speed)
- Data provider: yahoo
- Each iteration must complete in under 30 seconds