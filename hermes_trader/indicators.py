"""Technical indicators on pandas Series/DataFrames (OHLCV columns: open high low close volume)."""

from __future__ import annotations

import numpy as np
import pandas as pd


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def rsi(s: pd.Series, n: int = 14) -> pd.Series:
    delta = s.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = gain / loss.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    # no losses in window -> RSI 100
    return out.where(loss != 0, 100.0).where(gain.notna())


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    return pd.concat(
        [df["high"] - df["low"], (df["high"] - prev_close).abs(), (df["low"] - prev_close).abs()], axis=1
    ).max(axis=1)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    return true_range(df).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def bollinger(s: pd.Series, n: int = 20, k: float = 2.0) -> tuple[pd.Series, pd.Series, pd.Series]:
    mid = sma(s, n)
    sd = s.rolling(n, min_periods=n).std(ddof=0)
    return mid - k * sd, mid, mid + k * sd


def donchian(df: pd.DataFrame, n: int = 20) -> tuple[pd.Series, pd.Series]:
    """Channel of the *previous* n bars (shifted) so a breakout is detectable on the current bar."""
    return df["low"].rolling(n).min().shift(1), df["high"].rolling(n).max().shift(1)


def macd(s: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[pd.Series, pd.Series]:
    line = ema(s, fast) - ema(s, slow)
    return line, ema(line, signal)


def swing(df: pd.DataFrame, n: int = 55) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Swing range of the *previous* n bars: (low, high, up_leg).

    up_leg is True when the swing high came after the swing low (an up-move being retraced),
    False when the low came last (a down-move). Uses bars t-n..t-1 only, like donchian().
    """
    hi = df["high"].to_numpy(dtype=float)
    lo = df["low"].to_numpy(dtype=float)
    out_lo = np.full(len(df), np.nan)
    out_hi = np.full(len(df), np.nan)
    out_up = np.full(len(df), np.nan)
    if len(df) > n:
        from numpy.lib.stride_tricks import sliding_window_view

        wh, wl = sliding_window_view(hi, n)[:-1], sliding_window_view(lo, n)[:-1]  # windows ending at t-1
        # last occurrence of the extreme, so a re-test counts as the most recent swing point
        ih = n - 1 - np.argmax(wh[:, ::-1], axis=1)
        il = n - 1 - np.argmin(wl[:, ::-1], axis=1)
        out_hi[n:] = wh.max(axis=1)
        out_lo[n:] = wl.min(axis=1)
        out_up[n:] = (ih > il).astype(float)
    idx = df.index
    return pd.Series(out_lo, idx), pd.Series(out_hi, idx), pd.Series(out_up, idx)
