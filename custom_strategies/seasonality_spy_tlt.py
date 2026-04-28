from helpers.registry import register_strategy
import numpy as np


@register_strategy(
    name="SPY/TLT Seasonality Rotation",
    dependencies=["spy"],
    params={},
)
def spy_tlt_seasonality(df, **kwargs):
    """Seasonal rotation: long SPY Oct-Jun, long TLT Jul-Sep.

    Original strategy by Mo Nabil. Fixed signal convention:
    -1 = exit (not 0) so the position closes when switching assets.
    tlt dependency removed — only spy_df is needed for symbol detection.
    """
    spy_df = kwargs["spy_df"]
    spy_close = spy_df["Close"].reindex(df.index).ffill()
    current_close = df["Close"]

    # Detect which asset this df represents via correlation with SPY
    if np.corrcoef(current_close.fillna(0), spy_close.fillna(0))[0, 1] > 0.99:
        symbol = "SPY"
    else:
        symbol = "TLT"

    signal = np.zeros(len(df))
    for i in range(len(df)):
        month = df.index[i].month
        # SPY season: October (10) through June (6)
        target = "SPY" if (month >= 10 or month <= 6) else "TLT"
        signal[i] = 1 if symbol == target else -1

    df["Signal"] = signal
    return df
