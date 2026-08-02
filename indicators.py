# indicators.py

import pandas as pd


def calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """RSIを計算する。"""
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)

    average_gain = up.rolling(window=period).mean()
    average_loss = down.rolling(window=period).mean()

    return 100 - (100 / (1 + (average_gain / average_loss)))


def calc_macd(
    series: pd.Series,
    short_period: int = 12,
    long_period: int = 26,
    signal_period: int = 9,
) -> tuple[pd.Series, pd.Series]:
    """MACDとシグナルを計算する。"""
    short_ema = series.ewm(span=short_period, adjust=False).mean()
    long_ema = series.ewm(span=long_period, adjust=False).mean()

    macd = short_ema - long_ema
    signal = macd.ewm(span=signal_period, adjust=False).mean()

    return macd, signal