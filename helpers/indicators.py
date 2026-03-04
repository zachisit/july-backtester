# helpers/indicators.py

import pandas as pd
import numpy as np
import pandas_ta as ta

# ----
# Used for Scanner
def bollinger_band_scanner_logic(df, length=20, std_dev=2.5):
    """
    Scanner-friendly version of the Bollinger Band Fade logic.
    Returns discrete events, not a stateful signal.
    Signal 1: Price crossed BELOW the lower band on the last bar.
    Signal -1: Price crossed ABOVE the middle SMA on the last bar.
    Signal 0: No event.
    """
    # Use your canonical function to get the bands
    df = calculate_bollinger_bands(df, length, std_dev)
    
    # Drop NaNs to avoid errors on initial data points
    df.dropna(subset=[f'SMA_{length}', 'LowerBand'], inplace=True)
    if len(df) < 2: # Need at least two rows to check for a cross
        return 0

    # Get the last two rows of data for comparison
    last_bar = df.iloc[-1]
    prev_bar = df.iloc[-2]

    # --- Event-Based Signal Logic ---
    # BUY SIGNAL: Price was above the band, now it's below.
    buy_event = prev_bar['Close'] >= prev_bar['LowerBand'] and last_bar['Close'] < last_bar['LowerBand']
    
    # SELL SIGNAL: Price was below the SMA, now it's above.
    sell_event = prev_bar['Close'] <= prev_bar[f'SMA_{length}'] and last_bar['Close'] > last_bar[f'SMA_{length}']

    if buy_event:
        return 1
    if sell_event:
        return -1
    
    return 0
# --- End Scanner Specific

def buy_and_hold_logic(df):
    df['Signal'] = 1
    return df

def calculate_rsi(df, length=14):
    """Calculates RSI and adds an 'RSI_{length}' column to the DataFrame."""
    if f'RSI_{length}' not in df.columns:
        delta = df['Close'].diff()
        gain = delta.where(delta > 0, 0).ewm(alpha=1/length, adjust=False).mean()
        loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/length, adjust=False).mean()
        rs = gain / loss
        df[f'RSI_{length}'] = 100 - (100 / (1 + rs))
    return df

def calculate_bollinger_bands(df, length=20, std_dev=2):
    """Calculates Bollinger Bands and adds them to the DataFrame."""
    df = calculate_sma(df, length)
    df['StdDev'] = df['Close'].rolling(window=length).std()
    df['UpperBand'] = df[f'SMA_{length}'] + (df['StdDev'] * std_dev)
    df['LowerBand'] = df[f'SMA_{length}'] - (df['StdDev'] * std_dev)
    return df

def bollinger_band_logic_v2(df, length=20, std_dev=2.0, exit_target_band='upper'):
    """Enhanced Bollinger Band Fade strategy with a configurable exit target."""
    df = calculate_bollinger_bands(df, length, std_dev)
    buy_signal = df['Close'] < df['LowerBand']
    
    if exit_target_band == 'upper':
        sell_signal = df['Close'] > df['UpperBand']
    else:
        sell_signal = df['Close'] > df[f'SMA_{length}']

    df['Signal'] = np.where(buy_signal, 1, np.where(sell_signal, -1, 0))
    df['Signal'] = df['Signal'].replace(0, np.nan).ffill().fillna(0)
    return df

def bollinger_fade_with_regime_filter_logic(df, spy_df, length=20, std_dev=2.0, regime_ma=200):
    """
    Bollinger Band Fade strategy with a SPY-based trend filter.
    Only takes buy signals when the SPY is above its long-term moving average.
    """
    # 1. Get the base bollinger band signals from the core logic function
    df = bollinger_band_logic(df, length, std_dev)
    original_signal = df['Signal'].copy()
    
    # 2. Calculate the SPY trend filter state
    spy_sma_regime = spy_df['Close'].rolling(regime_ma).mean()
    
    # Align data to the primary symbol's index
    regime_df = pd.DataFrame(index=df.index)
    regime_df['spy_close'] = spy_df['Close']
    regime_df['spy_sma'] = spy_sma_regime
    regime_df.ffill(inplace=True)
    is_bull_market = regime_df['spy_close'] > regime_df['spy_sma']

    # 3. Apply the filter: only allow buy signals (1) during a bull market.
    #    Keep all original sell signals (-1) to ensure timely exits.
    df['Signal'] = np.where(
        (original_signal == 1) & is_bull_market, 
        1, 
        original_signal
    )
    
    # 4. Re-apply the forward-fill to maintain the state
    df['Signal'] = df['Signal'].replace(0, np.nan).ffill().fillna(0)
    return df

def atr_trailing_stop_with_trend_filter_logic(df, entry_period=20, atr_period=14, atr_multiplier=3.0, ma_length=200):
    """
    Combines a Donchian/Price Channel breakout entry with an ATR trailing stop
    and a long-term trend filter (SMA).

    *** IMPORTANT — KNOWN INTRABAR FILL ASSUMPTION ***
    This strategy detects entry using the current bar's High exceeding the
    breakout level, then records the fill at that same bar's Close. On daily
    bars this means entry is triggered intraday but filled at end-of-day,
    which is not achievable in live trading. Results will be optimistic
    compared to filling at the next bar's open.

    This strategy is safe to use for directional research but should NOT
    be used for precise entry-cost analysis on daily bars without modification.
    For a clean daily-bar version, move entry execution to the next bar's open
    by shifting the signal output and letting the simulation engine handle fill.
    """
    # 1. Calculate all necessary indicators
    df = calculate_sma(df, ma_length)
    df = calculate_atr(df, period=atr_period)
    df['entry_high'] = df['High'].rolling(window=entry_period).max().shift(1)

    # 2. Define the Trend Filter
    is_uptrend = df['Close'] > df[f'SMA_{ma_length}']

    # 3. Generate Signals
    events = pd.Series(0, index=df.index) # Use 0 for no event
    in_position = False
    trailing_stop_price = 0.0

    for i in range(1, len(df)):
        # Skip if data is not ready
        if pd.isna(df['entry_high'].iloc[i]) or pd.isna(df['ATR'].iloc[i]):
            continue
        
        # Check for Exit FIRST
        if in_position and (df['Low'].iloc[i] < trailing_stop_price or not is_uptrend.iloc[i]):
            events.iloc[i] = -1  # Exit event
            in_position = False
            trailing_stop_price = 0.0
            continue # Go to next day

        # Check for Entry
        if not in_position and is_uptrend.iloc[i] and df['High'].iloc[i] > df['entry_high'].iloc[i]:
            events.iloc[i] = 1  # Entry event
            in_position = True
            trailing_stop_price = df['Close'].iloc[i] - (df['ATR'].iloc[i] * atr_multiplier)
        
        # If in position, update the trailing stop
        if in_position:
            new_stop_price = df['Close'].iloc[i] - (df['ATR'].iloc[i] * atr_multiplier)
            trailing_stop_price = max(trailing_stop_price, new_stop_price)

    # 4. Convert event signals (1, -1, 0) into a stateful signal (1, -1)
    df['Signal'] = events.replace(0, np.nan).ffill().fillna(0).astype(int)
    
    return df

def ma_confluence_logic(df, ma_fast=10, ma_medium=20, ma_slow=50, entry_rule="full_stack", exit_rule="bearish_stack", **kwargs):
    """
    Final, flexible logic for MA Confluence with configurable entry and exit rules.
    """
    # 1. Calculate all necessary moving averages.
    df['MA_fast'] = df['Close'].rolling(window=ma_fast).mean()
    df['MA_medium'] = df['Close'].rolling(window=ma_medium).mean()
    df['MA_slow'] = df['Close'].rolling(window=ma_slow).mean()

    # 2. Define the ENTRY state based on the selected rule.
    if entry_rule == "fast_only":
        # New Aggressive Entry: Only requires Close and Fast MA to be above Slow MA.
        is_bullish_state = (
            (df['Close'] > df['MA_slow']) &
            (df['MA_fast'] > df['MA_slow'])
        )
    else: # Default to "full_stack"
        # Original, Proven Entry: Requires the full bullish stack.
        is_bullish_state = (
            (df['Close'] > df['MA_slow']) &
            (df['MA_fast'] > df['MA_slow']) &
            (df['MA_medium'] > df['MA_slow'])
        )
    
    # The entry event is always the first day this state becomes true.
    entry_event = (is_bullish_state.shift(1) == False) & (is_bullish_state == True)

    # 3. Define the EXIT event based on the selected rule.
    if exit_rule == "fast_cross":
        # Aggressive Exit: The first day the fast MA is below the slow MA.
        is_exit_state = df['MA_fast'] < df['MA_slow']
        exit_event = (is_exit_state.shift(1) == False) & (is_exit_state == True)
    elif exit_rule == "medium_cross":
        # Tighter Exit: The first day the Close is below the MEDIUM MA.
        is_exit_state = df['Close'] < df['MA_medium']
        exit_event = (is_exit_state.shift(1) == False) & (is_exit_state == True)
    else: # Default to "bearish_stack"
        # Original, Proven Exit: The first day the full bearish stack is true.
        is_bearish_state = (
            (df['Close'] < df['MA_slow']) &
            (df['MA_fast'] < df['MA_slow']) &
            (df['MA_medium'] < df['MA_slow'])
        )
        exit_event = (is_bearish_state.shift(1) == False) & (is_bearish_state == True)

    # 4. Create the signal based on these events and forward-fill the state.
    df['Signal'] = np.where(entry_event, 1, np.where(exit_event, -1, 0))
    df['Signal'] = df['Signal'].replace(0, np.nan).ffill().fillna(0)
    
    return df

def ma_confluence_with_regime_filter_logic(df, spy_df, vix_df, ma_fast=10, ma_medium=20, ma_slow=50, regime_ma=200, vix_threshold=30):
    """
    Combines the MA Confluence strategy with the SPY+VIX regime filter.
    
    - REGIME FILTER: SPY must be > its 200d SMA AND VIX must be < threshold.
    - ENTRY SETUP: Fast MA (10) and Medium MA (20) must both be above the Slow MA (50).
    - ENTRY TRIGGER: The first candle to close above the Slow MA (50) AFTER the setup is met.
    - EXIT: Any candle closes below the Slow MA (50).
    """
    # --- Part 1: Get the MA Confluence Signal (from ma_confluence_logic) ---
    
    # Calculate all necessary moving averages for the primary symbol
    df['MA_fast'] = df['Close'].rolling(window=ma_fast).mean()
    df['MA_medium'] = df['Close'].rolling(window=ma_medium).mean()
    df['MA_slow'] = df['Close'].rolling(window=ma_slow).mean()

    # Define the bullish stack condition
    is_bullish_stack = (
        (df['Close'] > df['MA_slow']) &
        (df['MA_fast'] > df['MA_slow']) &
        (df['MA_medium'] > df['MA_slow'])
    )
    
    # The entry event is the first day this state becomes true
    entry_event = (is_bullish_stack.shift(1) == False) & (is_bullish_stack == True)
    
    # The exit event is any close below the slow MA
    exit_event = df['Close'] < df['MA_slow']

    # --- Part 2: Get the Regime Filter State (from ema_regime_crossover_logic) ---

    # Calculate the market regime from SPY and VIX data
    spy_sma_regime = spy_df['Close'].rolling(window=regime_ma).mean()
    
    # Align data to the primary symbol's index
    regime_df = pd.DataFrame(index=df.index)
    regime_df['spy_close'] = spy_df['Close']
    regime_df['spy_sma'] = spy_sma_regime
    regime_df['vix_close'] = vix_df['Close']
    regime_df.ffill(inplace=True) # Forward-fill to handle any non-matching dates
    
    # The regime is "Bull-Quiet" if both conditions are true
    is_bull_quiet_regime = (regime_df['spy_close'] > regime_df['spy_sma']) & (regime_df['vix_close'] < vix_threshold)

    # --- Part 3: Combine the Logic ---
    
    # The final buy signal is only valid if the entry event happens AND the market is in a good regime.
    final_buy_signal = entry_event & is_bull_quiet_regime
    
    # We do not filter the exit. We always exit when the stock's own trend breaks.
    final_sell_signal = exit_event

    # --- Part 4: Generate the Final Stateful Signal Column ---
    df['Signal'] = np.where(final_buy_signal, 1, np.where(final_sell_signal, -1, 0))
    df['Signal'] = df['Signal'].replace(0, np.nan).ffill().fillna(0)
    
    return df

def ema_regime_crossover_logic(df, spy_df, vix_df, fast_ema=20, slow_ema=50, regime_ma=200, vix_threshold=30):
    """EMA Crossover, filtered by a "Bull-Quiet" market regime."""
    if fast_ema is None or slow_ema is None:
        raise ValueError("EMA Crossover strategy requires valid integer values for fast_ema and slow_ema.")
    df['EMA_fast'] = df['Close'].ewm(span=fast_ema, adjust=False).mean()
    df['EMA_slow'] = df['Close'].ewm(span=slow_ema, adjust=False).mean()
    spy_sma_regime = spy_df['Close'].rolling(regime_ma).mean()
    regime_df = pd.DataFrame(index=df.index)
    regime_df['spy_close'] = spy_df['Close']
    regime_df['spy_sma'] = spy_sma_regime
    regime_df['vix_close'] = vix_df['Close']
    regime_df.ffill(inplace=True)
    is_bull_quiet = (regime_df['spy_close'] > regime_df['spy_sma']) & (regime_df['vix_close'] < vix_threshold)
    buy_signal = (df['EMA_fast'].shift(1) <= df['EMA_slow'].shift(1)) & (df['EMA_fast'] > df['EMA_slow'])
    sell_signal = (df['EMA_fast'].shift(1) >= df['EMA_slow'].shift(1)) & (df['EMA_fast'] < df['EMA_slow'])
    filtered_buy = buy_signal & is_bull_quiet
    df['Signal'] = np.where(filtered_buy, 1, np.where(sell_signal, -1, 0))
    df['Signal'] = df['Signal'].replace(0, np.nan).ffill().fillna(0)
    return df

def sma_crossover_logic(df, fast, slow):
    df['SMA_fast'] = df['Close'].rolling(fast).mean()
    df['SMA_slow'] = df['Close'].rolling(slow).mean()
    df['Signal'] = np.where(df['SMA_fast'] > df['SMA_slow'], 1, -1)
    return df

def rsi_logic(df, length, oversold, exit_level):
    delta = df['Close'].diff()
    gain = delta.where(delta > 0, 0).ewm(alpha=1/length, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/length, adjust=False).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    # CORRECTED LOGIC: Buy when RSI crosses back UP over the oversold line
    buy_signal = (df['RSI'].shift(1) < oversold) & (df['RSI'] >= oversold)
    # Exit when RSI crosses back UP over the mid-line (return to mean)
    sell_signal = (df['RSI'].shift(1) <= exit_level) & (df['RSI'] > exit_level)
    df['Signal'] = np.where(buy_signal, 1, np.where(sell_signal, -1, 0))
    df['Signal'] = df['Signal'].replace(0, np.nan).ffill().fillna(0)
    return df

def macd_crossover_logic(df, fast, slow, signal):
    df['EMA_fast'] = df['Close'].ewm(span=fast, adjust=False).mean()
    df['EMA_slow'] = df['Close'].ewm(span=slow, adjust=False).mean()
    df['MACD'] = df['EMA_fast'] - df['EMA_slow']
    df['Signal_Line'] = df['MACD'].ewm(span=signal, adjust=False).mean()
    df['Signal'] = np.where(df['MACD'] > df['Signal_Line'], 1, -1)
    return df

def bollinger_band_logic(df, length=20, std_dev=2.0):
    """Original Bollinger Band Fade strategy."""
    df = calculate_bollinger_bands(df, length, std_dev)
    buy_signal = df['Close'] < df['LowerBand']
    sell_signal = df['Close'] > df[f'SMA_{length}']
    df['Signal'] = np.where(buy_signal, 1, np.where(sell_signal, -1, 0))
    df['Signal'] = df['Signal'].replace(0, np.nan).ffill().fillna(0)
    return df

def stochastic_logic(df, length, k_smooth, oversold, exit_level):
    df['L14'] = df['Low'].rolling(length).min()
    df['H14'] = df['High'].rolling(length).max()
    df['%K'] = 100 * ((df['Close'] - df['L14']) / (df['H14'] - df['L14']))
    df['%D'] = df['%K'].rolling(k_smooth).mean()
    # CORRECTED LOGIC: Buy when %K crosses back UP over the oversold line
    buy_signal = (df['%K'].shift(1) < oversold) & (df['%K'] >= oversold)
    # Exit when %K crosses back UP over the mid-line (return to mean)
    sell_signal = (df['%K'].shift(1) <= exit_level) & (df['%K'] > exit_level)
    df['Signal'] = np.where(buy_signal, 1, np.where(sell_signal, -1, 0))
    df['Signal'] = df['Signal'].replace(0, np.nan).ffill().fillna(0)
    return df

def bollinger_breakout_logic(df, length, std_dev):
    df['SMA'] = df['Close'].rolling(length).mean()
    df['StdDev'] = df['Close'].rolling(length).std()
    df['UpperBand'] = df['SMA'] + (df['StdDev'] * std_dev)
    buy_signal = df['Close'] > df['UpperBand']
    sell_signal = df['Close'] < df['SMA']
    df['Signal'] = np.where(buy_signal, 1, np.where(sell_signal, -1, 0))
    df['Signal'] = df['Signal'].replace(0, np.nan).ffill().fillna(0)
    return df

def roc_logic(df, length, threshold=0):
    df['ROC'] = df['Close'].pct_change(periods=length) * 100
    df['Signal'] = np.where(df['ROC'] > threshold, 1, -1)
    return df

def sma_trend_filter_logic(df, ma_length=200):
    df['MA'] = df['Close'].rolling(ma_length).mean()
    df['Signal'] = np.where(df['Close'] > df['MA'], 1, -1)
    return df

def donchian_channel_breakout_logic(df, entry_period=20, exit_period=10):
    df['Upper'] = df['High'].shift(1).rolling(entry_period).max()
    df['Lower'] = df['Low'].shift(1).rolling(exit_period).min()
    buy_signal = df['Close'] > df['Upper']
    sell_signal = df['Close'] < df['Lower']
    df['Signal'] = np.where(buy_signal, 1, np.where(sell_signal, -1, 0))
    df['Signal'] = df['Signal'].replace(0, np.nan).ffill().fillna(0)
    return df

def obv_logic(df, ma_length=20):
    """
    Baseline OBV Strategy.
    Signal is 1 (long) whenever OBV > its SMA, -1 otherwise.
    """
    # This line will now work correctly
    df.ta.obv(append=True) # Calculates and adds 'OBV' column
    df['OBV_MA'] = df['OBV'].rolling(ma_length).mean()
    df['Signal'] = np.where(df['OBV'] > df['OBV_MA'], 1, -1)
    return df

def daily_overnight_logic(df):
    """
    Buys at every close and sells at the next open.
    The simulation engine handles the execution based on its settings.
    """
    # Always be in a position. Signal is always 1.
    # The backtester will handle buying/selling at close/open.
    # This requires setting execution_time = "close" for entry 
    # and "open" for exit in the simulation engine itself.
    # A simpler approximation is a signal that's always on.
    df['Signal'] = 1 
    return df

def weekday_overnight_with_vix_filter_logic(df, vix_df, vix_threshold=20):
    """Applies weekday overnight, but only buys if VIX is below a threshold."""
    df = weekday_overnight_logic(df)
    original_signal = df['Signal'].copy()
    if vix_df is None:
        return df
    aligned_vix = vix_df.reindex(df.index, method='ffill')
    is_market_calm = aligned_vix['Close'] < vix_threshold
    df['Signal'] = np.where((original_signal == 1) & is_market_calm, 1, -1)
    return df

def weekday_overnight_with_trend_filter_logic(df, ma_length=20):
    """
    Applies the weekday overnight logic, but only takes buy signals if the
    asset is in a short-term uptrend (Close > SMA).
    """
    # 1. Get the base weekday overnight signals
    df = weekday_overnight_logic(df)
    
    # 2. Get the trend filter condition
    df = calculate_sma(df, ma_length)
    is_uptrend = df['Close'] > df[f'SMA_{ma_length}']
    
    # 3. Apply the filter
    # Only allow a buy signal (1) if in an uptrend. Otherwise, force to flat (-1).
    df['Signal'] = np.where((df['Signal'] == 1) & is_uptrend, 1, -1)
    
    return df

def weekday_overnight_with_rsi_filter_logic(df, rsi_length=14, rsi_threshold=40):
    """
    Applies the weekday overnight logic, but only takes buy signals if the
    asset is in a low-momentum or oversold state (RSI < Threshold).
    """
    # 1. Get the base weekday overnight signals
    df = weekday_overnight_logic(df)
    
    # 2. Get the RSI filter condition
    df = calculate_rsi(df, rsi_length)
    is_oversold = df[f'RSI_{rsi_length}'] < rsi_threshold
    
    # 3. Apply the filter
    df['Signal'] = np.where((df['Signal'] == 1) & is_oversold, 1, -1)
    
    return df

# --- OPTION 1: OBV Trend with Price Confirmation (The "Confluence" Filter) ---
def obv_price_confirmation_logic(df, obv_ma_length=20, price_ma_length=20):
    """
    Enhanced OBV Strategy.
    ENTRY: OBV crosses above its SMA.
    EXIT: OBV crosses below its SMA AND Price also closes below its own EMA.
    This requires a stateful, iterative calculation.
    """
    # 1. Calculate all necessary indicators
    df.ta.obv(append=True)
    df['OBV_MA'] = df['OBV'].rolling(obv_ma_length).mean()
    df['Price_MA'] = ta.ema(df['Close'], length=price_ma_length)

    # 2. Loop through the data to determine the state (in or out of a trade)
    signals = []
    in_position = False
    for i in range(len(df)):
        # Handle the start of the series where we don't have enough data
        if i == 0 or pd.isna(df['OBV_MA'].iloc[i-1]):
            signals.append(-1)
            continue

        # --- Entry Logic (An EVENT) ---
        # OBV crosses from below to above its MA
        if not in_position and df['OBV'].iloc[i] > df['OBV_MA'].iloc[i] and df['OBV'].iloc[i-1] <= df['OBV_MA'].iloc[i-1]:
            in_position = True
        
        # --- Exit Logic (A more robust EVENT) ---
        # OBV crosses from above to below its MA AND price confirms weakness
        elif in_position and df['OBV'].iloc[i] < df['OBV_MA'].iloc[i] and df['Close'].iloc[i] < df['Price_MA'].iloc[i]:
            in_position = False

        # Set the signal for the current day based on the state
        signals.append(1 if in_position else -1)

    df['Signal'] = signals
    return df

# --- OPTION 2: OBV Trend with Confirmation Period (The "Wait and See" Filter) ---
def obv_confirmation_period_logic(df, ma_length=20, confirmation_days=2):
    """
    Enhanced OBV Strategy.
    ENTRY: OBV crosses above its SMA.
    EXIT: OBV stays below its SMA for a set number of consecutive days.
    """
    # 1. Calculate indicators
    df.ta.obv(append=True)
    df['OBV_MA'] = df['OBV'].rolling(ma_length).mean()
    
    # 2. Create a helper column for the exit condition
    df['is_obv_below'] = df['OBV'] < df['OBV_MA']
    # Check for N consecutive days of being below
    df['exit_trigger'] = df['is_obv_below'].rolling(window=confirmation_days).sum() == confirmation_days

    # 3. Loop to determine state
    signals = []
    in_position = False
    for i in range(len(df)):
        if i == 0 or pd.isna(df['OBV_MA'].iloc[i-1]):
            signals.append(-1)
            continue

        # --- Entry Logic (An EVENT) ---
        if not in_position and df['OBV'].iloc[i] > df['OBV_MA'].iloc[i] and df['OBV'].iloc[i-1] <= df['OBV_MA'].iloc[i-1]:
            in_position = True
        
        # --- Exit Logic (An EVENT based on the trigger column) ---
        elif in_position and df['exit_trigger'].iloc[i]:
            in_position = False

        signals.append(1 if in_position else -1)
    
    df['Signal'] = signals
    return df

def macd_rsi_filter_logic(df, macd_fast, macd_slow, macd_signal, rsi_length):
    df['EMA_fast'] = df['Close'].ewm(span=macd_fast, adjust=False).mean()
    df['EMA_slow'] = df['Close'].ewm(span=macd_slow, adjust=False).mean()
    df['MACD'] = df['EMA_fast'] - df['EMA_slow']
    df['Signal_Line'] = df['MACD'].ewm(span=macd_signal, adjust=False).mean()
    delta = df['Close'].diff()
    gain = delta.where(delta > 0, 0).ewm(alpha=1/rsi_length, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/rsi_length, adjust=False).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    macd_cross_up = (df['MACD'].shift(1) <= df['Signal_Line'].shift(1)) & (df['MACD'] > df['Signal_Line'])
    macd_cross_down = (df['MACD'].shift(1) >= df['Signal_Line'].shift(1)) & (df['MACD'] < df['Signal_Line'])
    buy_signal = macd_cross_up & (df['RSI'] > 50)
    df['Signal'] = np.where(buy_signal, 1, np.where(macd_cross_down, -1, 0))
    df['Signal'] = df['Signal'].replace(0, np.nan).ffill().fillna(0)
    return df

def ma_bounce_logic(df, ma_length=20, filter_bars=2):
    df['MA'] = df['Close'].rolling(ma_length).mean()
    is_below_ma = df['Close'] < df['MA']
    df['consecutive_below'] = is_below_ma.rolling(window=filter_bars).sum()
    downtrend_confirmed = df['consecutive_below'] == filter_bars
    bounce_candle = (df['Low'] <= df['MA']) & (df['Close'] > df['MA'])
    buy_signal = bounce_candle & ~downtrend_confirmed
    sell_signal = downtrend_confirmed
    df['Signal'] = np.where(buy_signal, 1, np.where(sell_signal, -1, 0))
    df['Signal'] = df['Signal'].replace(0, np.nan).ffill().fillna(0)
    return df

def weekday_overnight_logic(df):
    """Generates a stateful signal to be long Mon-Thu nights."""
    df['weekday'] = df.index.dayofweek
    buy_days = [0, 1, 2, 3] # Mon, Tue, Wed, Thu
    df['Signal'] = np.where(df['weekday'].isin(buy_days), 1, -1)
    return df

def atr_trailing_stop_logic(df, atr_period=14, atr_multiplier=3.0):
    """
    A volatility-based trailing stop strategy using a 200-day SMA for entry.
    - Entry: Buys when Close crosses above the 200 SMA.
    - Exit: Sells when the price closes below a dynamic ATR trailing stop.
    """
    # 1. Calculate indicators
    df = calculate_atr(df, period=atr_period)
    df['SMA200'] = df['Close'].rolling(200).mean()
    
    # --- NEW: SAFETY CHECK ---
    # Create a temporary dataframe with rows where our indicators are valid
    valid_data_df = df.dropna(subset=['SMA200', 'ATR'])
    # If this dataframe is empty, it means we don't have enough data to run the strategy.
    if valid_data_df.empty:
        # Return a DataFrame with a "do nothing" signal.
        df['Signal'] = 0 
        return df
    # --- END OF SAFETY CHECK ---
    
    base_entry_signal = (df['Close'] > df['SMA200']) & (df['Close'].shift(1) <= df['SMA200'].shift(1))

    # 2. Iteratively calculate the trailing stop and generate stateful signals
    signal = pd.Series(0, index=df.index)
    in_position = False
    trailing_stop_price = 0.0
    
    # Get the start index from our now-guaranteed-to-be-non-empty valid_data_df
    first_valid_index = df.index.get_loc(valid_data_df.index[0])

    for i in range(first_valid_index, len(df)):
        # --- CHECK FOR EXIT FIRST ---
        if in_position and df['Low'].iloc[i] < trailing_stop_price:
            in_position = False
            trailing_stop_price = 0.0
        
        # --- CHECK FOR ENTRY ---
        if not in_position and base_entry_signal.iloc[i]:
            in_position = True
            trailing_stop_price = df['Close'].iloc[i] - (df['ATR'].iloc[i] * atr_multiplier)
            
        # --- UPDATE TRAILING STOP if still in position ---
        if in_position:
            new_stop_price = df['Close'].iloc[i] - (df['ATR'].iloc[i] * atr_multiplier)
            trailing_stop_price = max(trailing_stop_price, new_stop_price)

        if in_position:
            signal.iloc[i] = 1
        else:
            signal.iloc[i] = 0

    df['Signal'] = np.where(signal.diff() == -1, -1, signal)
    df['Signal'] = df['Signal'].replace(0, np.nan).ffill().fillna(0)
    
    return df

def hold_the_week_logic(df):
    """
    This strategy buys at the market open on Tuesday and sells at the market open on Friday.
    It is designed to capture the intra-week drift.
    """
    df['weekday'] = df.index.dayofweek
    
    # A signal on Monday (0) triggers a buy at the next bar's open (Tuesday).
    buy_signal = df['weekday'] == 0
    
    # A signal on Thursday (3) triggers a sell at the next bar's open (Friday).
    sell_signal = df['weekday'] == 3
    
    df['Signal'] = np.where(buy_signal, 1, np.where(sell_signal, -1, 0))
    # Forward-fill the signal to hold the position for the entire period.
    df['Signal'] = df['Signal'].replace(0, np.nan).ffill().fillna(0)
    
    return df

def weekend_hold_logic(df):
    """
    Approximation of holding a position over the weekend.
    - Entry: Buy at Friday's open.
    - Exit: Sell at Monday's open.
    """
    df['weekday'] = df.index.dayofweek
    buy_signal = df['weekday'] == 3  # Signal on Thursday triggers buy on Friday open
    sell_signal = df['weekday'] == 4 # Signal on Friday triggers sell on Monday open
    df['Signal'] = np.where(buy_signal, 1, np.where(sell_signal, -1, 0))
    df['Signal'] = df['Signal'].replace(0, np.nan).ffill().fillna(0)
    return df

def keltner_channel_breakout_logic(df, ema_length=20, atr_length=20, atr_multiplier=2.0):
    """
    Keltner Channel Breakout Strategy.
    - Entry: Buys when the price closes above the upper Keltner Channel.
    - Exit: Sells when the price closes below the middle EMA line.
    """
    # Calculate Middle Line (EMA) and ATR
    df['EMA'] = df['Close'].ewm(span=ema_length, adjust=False).mean()
    high_low = df['High'] - df['Low']
    high_close = np.abs(df['High'] - df['Close'].shift())
    low_close = np.abs(df['Low'] - df['Close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = np.max(ranges, axis=1)
    df['ATR'] = true_range.ewm(alpha=1/atr_length, adjust=False).mean()

    # Calculate Keltner Channel Bands
    df['UpperBand'] = df['EMA'] + (df['ATR'] * atr_multiplier)
    
    # Generate signals
    buy_signal = df['Close'] > df['UpperBand']
    sell_signal = df['Close'] < df['EMA']
    
    df['Signal'] = np.where(buy_signal, 1, np.where(sell_signal, -1, 0))
    df['Signal'] = df['Signal'].replace(0, np.nan).ffill().fillna(0)
    
    return df

def chaikin_money_flow_with_stop_loss_logic(df, length=20, buy_threshold=0.05, sell_threshold=-0.05, stop_loss_pct=0.03):
    """
    Wrapper function that applies a fixed percentage stop-loss to the
    output of the standard Chaikin Money Flow strategy.
    """
    # 1. Get the original, stateless signals from the base strategy
    df_base = chaikin_money_flow_logic(df.copy(), length, buy_threshold, sell_threshold)
    
    # 2. Extract just the entry and exit events (ignore the ffill part)
    # A buy event is a change from not 1 to 1.
    # A sell event is a change from not -1 to -1.
    base_signal = df_base['Signal'].diff().fillna(0)
    entry_event = base_signal == 1
    exit_event = base_signal == -2 # A change from 1 to -1 is a diff of -2
    
    # 3. Iteratively process signals to include the stop-loss
    events = pd.Series(0, index=df.index)
    in_position = False
    entry_price = 0.0

    for i in range(1, len(df)):
        stop_loss_price = entry_price * (1 - stop_loss_pct)

        # --- CHECK EXIT CONDITIONS FIRST ---
        if in_position:
            # Exit due to stop-loss
            if df['Low'].iloc[i] < stop_loss_price:
                events.iloc[i] = -1
                in_position = False
                continue
            # Exit due to primary CMF signal
            if exit_event.iloc[i]:
                events.iloc[i] = -1
                in_position = False
                continue
        
        # --- CHECK ENTRY CONDITION ---
        if not in_position and entry_event.iloc[i]:
            events.iloc[i] = 1
            in_position = True
            entry_price = df['Close'].iloc[i]

    # 4. Convert events to a stateful signal for the scanner
    df['Signal'] = events.replace(0, np.nan).ffill().fillna(0).astype(int)
    
    return df

def chaikin_money_flow_logic(df, length=20, buy_threshold=0.05, sell_threshold=-0.05):
    """
    Chaikin Money Flow (CMF) Strategy.
    - Entry: Buys when CMF crosses above the buy_threshold.
    - Exit: Sells when CMF crosses below the sell_threshold.
    """
    # Calculate Money Flow Multiplier and Volume
    mfm = ((df['Close'] - df['Low']) - (df['High'] - df['Close'])) / (df['High'] - df['Low'])
    mfm = mfm.fillna(0)
    mfv = mfm * df['Volume']

    # Calculate CMF
    df['CMF'] = mfv.rolling(length).sum() / df['Volume'].rolling(length).sum()
    
    # Generate signals based on a crossover
    buy_signal = (df['CMF'].shift(1) < buy_threshold) & (df['CMF'] >= buy_threshold)
    sell_signal = (df['CMF'].shift(1) > sell_threshold) & (df['CMF'] <= sell_threshold)
    
    df['Signal'] = np.where(buy_signal, 1, np.where(sell_signal, -1, 0))
    df['Signal'] = df['Signal'].replace(0, np.nan).ffill().fillna(0)
    
    return df

def calculate_atr(df, period=14):
    """Calculates ATR and adds an 'ATR' column to the DataFrame."""
    if 'ATR' not in df.columns:
        high_low = df['High'] - df['Low']
        high_close = np.abs(df['High'] - df['Close'].shift())
        low_close = np.abs(df['Low'] - df['Close'].shift())
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df['ATR'] = tr.ewm(alpha=1/period, adjust=False).mean()
    return df

def calculate_sma(df, length):
    """Calculates SMA and adds a column 'SMA_{length}' to the DataFrame."""
    if f'SMA_{length}' not in df.columns:
        df[f'SMA_{length}'] = df['Close'].rolling(window=length).mean()
    return df

def atr_trailing_stop_logic_breakout_entry(df, entry_period=20, atr_period=14, atr_multiplier=3.0):
    """
    Corrected ATR Trailing Stop strategy with Donchian Breakout Entry.

    *** IMPORTANT — KNOWN INTRABAR FILL ASSUMPTION ***
    This strategy detects entry using the current bar's High exceeding the
    breakout level, then records the fill at that same bar's Close. On daily
    bars this means entry is triggered intraday but filled at end-of-day,
    which is not achievable in live trading. Results will be optimistic
    compared to filling at the next bar's open.

    This strategy is safe to use for directional research but should NOT
    be used for precise entry-cost analysis on daily bars without modification.
    For a clean daily-bar version, move entry execution to the next bar's open
    by shifting the signal output and letting the simulation engine handle fill.
    """
    # 1. Calculate indicators
    df = calculate_atr(df, period=atr_period)
    df['entry_high'] = df['High'].rolling(window=entry_period).max().shift(1)

    # --- NEW: SAFETY CHECK ---
    valid_data_df = df.dropna(subset=['entry_high', 'ATR'])
    if valid_data_df.empty:
        df['Signal'] = 0
        return df
    # --- END OF SAFETY CHECK ---

    # 2. Iteratively calculate the trailing stop and generate stateful signals
    signals = []
    in_position = False
    trailing_stop = 0.0

    first_valid_index = df.index.get_loc(valid_data_df.index[0])

    for i in range(first_valid_index, len(df)):
        # --- CHECK FOR EXIT FIRST ---
        if in_position and df['Low'].iloc[i] < trailing_stop:
            in_position = False
            trailing_stop = 0.0
        
        # --- CHECK FOR ENTRY ---
        if not in_position and df['High'].iloc[i] > df['entry_high'].iloc[i]:
            in_position = True
            trailing_stop = df['Close'].iloc[i] - (df['ATR'].iloc[i] * atr_multiplier)
            
        # --- UPDATE TRAILING STOP if still in position ---
        if in_position:
            new_stop = df['Close'].iloc[i] - (df['ATR'].iloc[i] * atr_multiplier)
            trailing_stop = max(trailing_stop, new_stop)

        signals.append(1 if in_position else 0)

    final_signals = pd.Series(signals, index=df.index)
    df['Signal'] = np.where(final_signals.diff() == -1, -1, final_signals)
    df['Signal'] = df['Signal'].replace(0, np.nan).ffill().fillna(0)
    
    return df

def bollinger_band_squeeze_logic(df, length=20, std_dev=2.0, squeeze_length=40):
    """
    Bollinger Band Squeeze Breakout Strategy.
    - Entry: Buys when price closes above the upper band AFTER a volatility squeeze.
    - Exit: Sells when price closes below the middle SMA line.
    """
    # 1. Calculate Bollinger Bands
    df['SMA'] = df['Close'].rolling(length).mean()
    df['StdDev'] = df['Close'].rolling(length).std()
    df['UpperBand'] = df['SMA'] + (df['StdDev'] * std_dev)
    df['LowerBand'] = df['SMA'] - (df['StdDev'] * std_dev)
    
    # 2. Identify the squeeze
    df['Bandwidth'] = (df['UpperBand'] - df['LowerBand']) / df['SMA']
    df['Lowest_Bandwidth'] = df['Bandwidth'].rolling(squeeze_length).min()
    squeeze_on = df['Bandwidth'] == df['Lowest_Bandwidth']
    
    # 3. Generate Signals
    buy_signal = (df['Close'] > df['UpperBand']) & squeeze_on.shift(1)
    sell_signal = df['Close'] < df['SMA']
    
    df['Signal'] = np.where(buy_signal, 1, np.where(sell_signal, -1, 0))
    df['Signal'] = df['Signal'].replace(0, np.nan).ffill().fillna(0)
    return df

def rsi_with_trend_filter_logic(df, rsi_length=14, oversold=30, exit_level=50, ma_length=200):
    """
    RSI Mean Reversion with a long-term SMA trend filter.
    - Entry: Buys when RSI crosses up over the oversold line, ONLY if Close > 200-day SMA.
    - Exit: Sells when RSI crosses up over the mid-line.
    """
    # 1. Calculate Indicators
    delta = df['Close'].diff()
    gain = delta.where(delta > 0, 0).ewm(alpha=1/rsi_length, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/rsi_length, adjust=False).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    df['SMA_Filter'] = df['Close'].rolling(ma_length).mean()

    # 2. Define conditions
    is_uptrend = df['Close'] > df['SMA_Filter']
    rsi_buy_cross = (df['RSI'].shift(1) < oversold) & (df['RSI'] >= oversold)
    rsi_sell_cross = (df['RSI'].shift(1) <= exit_level) & (df['RSI'] > exit_level)

    # 3. Generate signals
    buy_signal = is_uptrend & rsi_buy_cross
    sell_signal = rsi_sell_cross
    
    df['Signal'] = np.where(buy_signal, 1, np.where(sell_signal, -1, 0))
    df['Signal'] = df['Signal'].replace(0, np.nan).ffill().fillna(0)
    return df

def rsi_scalping_logic(df, rsi_length=14, oversold_level=20, overbought_level=80):
    """
    A 1-minute mean-reversion scalping strategy using extreme RSI levels.
    - Entry (Long): RSI crosses up from below the oversold level.
    - Exit (Long): RSI crosses up past the 50 midline.
    - Entry (Short): RSI crosses down from above the overbought level.
    - Exit (Short): RSI crosses down past the 50 midline.
    """
    # 1. Calculate RSI
    df = calculate_rsi(df, length=rsi_length)
    rsi_col = f'RSI_{rsi_length}'

    # 2. Define crossover events
    buy_entry = (df[rsi_col].shift(1) < oversold_level) & (df[rsi_col] >= oversold_level)
    buy_exit = (df[rsi_col].shift(1) < 50) & (df[rsi_col] >= 50)
    
    sell_entry = (df[rsi_col].shift(1) > overbought_level) & (df[rsi_col] <= overbought_level)
    sell_exit = (df[rsi_col].shift(1) > 50) & (df[rsi_col] <= 50)

    # 3. Generate stateful signal (this requires careful state management)
    signals = pd.Series(0, index=df.index)
    in_long = False
    in_short = False

    for i in range(1, len(df)):
        # Handle Long Position
        if not in_long and buy_entry.iloc[i]:
            in_long = True
        elif in_long and buy_exit.iloc[i]:
            in_long = False
        
        # Handle Short Position
        if not in_short and sell_entry.iloc[i]:
            in_short = True
        elif in_short and sell_exit.iloc[i]:
            in_short = False
            
        if in_long:
            signals.iloc[i] = 1
        elif in_short:
            signals.iloc[i] = -1 # Note: Your backtester may only support long trades
        else:
            signals.iloc[i] = 0
            
    # Convert events to state and then back to entry/exit signals for the backtester
    final_signal = signals.diff().fillna(0)
    df['Signal'] = final_signal.replace(-2, -1).replace(2, 1) # Handle short signals if needed
    df['Signal'] = df['Signal'].replace(0, np.nan).ffill().fillna(0)

    return df

def ema_scalping_logic(df, fast_ema_period=5, slow_ema_period=15, trend_ema_period=50):
    """
    A 1-minute EMA crossover scalping strategy with a long-term trend filter.
    - Entry: Fast EMA crosses above Slow EMA, only if price is above the Trend EMA.
    - Exit: Fast EMA crosses below Slow EMA.
    """
    # 1. Calculate all three EMAs
    df['EMA_fast'] = df['Close'].ewm(span=fast_ema_period, adjust=False).mean()
    df['EMA_slow'] = df['Close'].ewm(span=slow_ema_period, adjust=False).mean()
    df['EMA_trend'] = df['Close'].ewm(span=trend_ema_period, adjust=False).mean()

    # 2. Define the trend condition
    is_uptrend = df['Close'] > df['EMA_trend']

    # 3. Define the crossover events
    buy_cross = (df['EMA_fast'].shift(1) <= df['EMA_slow'].shift(1)) & (df['EMA_fast'] > df['EMA_slow'])
    sell_cross = (df['EMA_fast'].shift(1) >= df['EMA_slow'].shift(1)) & (df['EMA_fast'] < df['EMA_slow'])

    # 4. Apply the trend filter to the buy signal
    filtered_buy = buy_cross & is_uptrend

    # 5. Generate the stateful signal
    df['Signal'] = np.where(filtered_buy, 1, np.where(sell_cross, -1, 0))
    df['Signal'] = df['Signal'].replace(0, np.nan).ffill().fillna(0)
    
    return df

def ema_crossover_unfiltered_logic(df, fast_ema, slow_ema):
    """
    A pure, unfiltered EMA Crossover strategy.
    - Entry: Fast EMA crosses above Slow EMA.
    - Exit: Fast EMA crosses below Slow EMA.
    """
    if fast_ema is None or slow_ema is None:
        raise ValueError("EMA Crossover strategy requires valid integer values for fast_ema and slow_ema.")
    
    df['EMA_fast'] = df['Close'].ewm(span=fast_ema, adjust=False).mean()
    df['EMA_slow'] = df['Close'].ewm(span=slow_ema, adjust=False).mean()
    
    buy_signal = (df['EMA_fast'].shift(1) <= df['EMA_slow'].shift(1)) & (df['EMA_fast'] > df['EMA_slow'])
    sell_signal = (df['EMA_fast'].shift(1) >= df['EMA_slow'].shift(1)) & (df['EMA_fast'] < df['EMA_slow'])
    
    df['Signal'] = np.where(buy_signal, 1, np.where(sell_signal, -1, 0))
    df['Signal'] = df['Signal'].replace(0, np.nan).ffill().fillna(0)
    return df

def ema_crossover_spy_only_logic(df, spy_df, fast_ema, slow_ema, regime_ma=200):
    """EMA Crossover, filtered ONLY by a SPY trend regime."""
    # Get the base signal from the unfiltered version
    df = ema_crossover_unfiltered_logic(df, fast_ema, slow_ema)
    original_signal = df['Signal'].copy()
    
    # Calculate the SPY trend filter
    spy_sma_regime = spy_df['Close'].rolling(window=regime_ma).mean()
    regime_df = pd.DataFrame(index=df.index)
    regime_df['spy_close'] = spy_df['Close']
    regime_df['spy_sma'] = spy_sma_regime
    regime_df.ffill(inplace=True)
    is_bull_market = regime_df['spy_close'] > regime_df['spy_sma']

    # Apply the filter only to buy signals
    df['Signal'] = np.where((original_signal == 1) & is_bull_market, 1, original_signal)
    df['Signal'] = df['Signal'].replace(0, np.nan).ffill().fillna(0)
    return df

def ema_crossover_vix_only_logic(df, vix_df, fast_ema, slow_ema, vix_threshold=30):
    """EMA Crossover, filtered ONLY by a VIX volatility regime."""
    df = ema_crossover_unfiltered_logic(df, fast_ema, slow_ema)
    original_signal = df['Signal'].copy()
    
    # Calculate the VIX volatility filter
    regime_df = pd.DataFrame(index=df.index)
    regime_df['vix_close'] = vix_df['Close']
    regime_df.ffill(inplace=True)
    is_market_calm = regime_df['vix_close'] < vix_threshold

    # Apply the filter only to buy signals
    df['Signal'] = np.where((original_signal == 1) & is_market_calm, 1, original_signal)
    df['Signal'] = df['Signal'].replace(0, np.nan).ffill().fillna(0)
    return df