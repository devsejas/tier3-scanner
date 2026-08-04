"""
indicators.py — Indicadores técnicos calculados igual que en Pine Script (TradingView).
Usa suavizado de Wilder (RMA) donde corresponde, para que los valores coincidan
con ta.rsi, ta.atr y ta.dmi de Pine.
"""
import pandas as pd
import numpy as np


def ema(series: pd.Series, period: int) -> pd.Series:
    """EMA estándar (igual que ta.ema en Pine)."""
    return series.ewm(span=period, adjust=False).mean()


def rma(series: pd.Series, period: int) -> pd.Series:
    """Suavizado de Wilder (RMA) — usado por ta.rsi, ta.atr y ta.dmi en Pine."""
    return series.ewm(alpha=1 / period, adjust=False).mean()


def rsi(closes: pd.Series, period: int = 14) -> pd.Series:
    """RSI de Wilder (igual que ta.rsi)."""
    delta = closes.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = rma(gain, period)
    avg_loss = rma(loss, period)
    rs = avg_gain / avg_loss.replace(0, np.nan)
    result = 100 - (100 / (1 + rs))
    result = result.fillna(100)  # si avg_loss es 0, RSI = 100
    return result


def macd(closes: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """MACD estándar (igual que ta.macd)."""
    macd_line = ema(closes, fast) - ema(closes, slow)
    signal_line = ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range con suavizado de Wilder (igual que ta.atr)."""
    high, low, close = df['high'], df['low'], df['close']
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return rma(tr, period)


def dmi(df: pd.DataFrame, period: int = 14):
    """ADX / +DI / -DI con suavizado de Wilder (igual que ta.dmi(len, len))."""
    high, low, close = df['high'], df['low'], df['close']
    prev_high, prev_low, prev_close = high.shift(1), low.shift(1), close.shift(1)

    up_move = high - prev_high
    down_move = prev_low - low

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)

    smoothed_tr = rma(tr, period)
    smoothed_plus_dm = rma(pd.Series(plus_dm, index=df.index), period)
    smoothed_minus_dm = rma(pd.Series(minus_dm, index=df.index), period)

    plus_di = 100 * (smoothed_plus_dm / smoothed_tr.replace(0, np.nan))
    minus_di = 100 * (smoothed_minus_dm / smoothed_tr.replace(0, np.nan))

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = rma(dx.fillna(0), period)

    return adx, plus_di, minus_di


def percentrank(series: pd.Series, period: int) -> pd.Series:
    """Percentil del valor actual respecto a la ventana (igual que ta.percentrank)."""
    def _rank(window):
        if len(window) < 2:
            return np.nan
        current = window[-1]
        return (window < current).sum() / (len(window) - 1) * 100

    return series.rolling(period).apply(_rank, raw=True)
